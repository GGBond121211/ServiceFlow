from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.agent.tool_registry import ToolDefinition, ToolRegistry
from serviceflow.application.case_service import CaseService
from serviceflow.application.operation_service import OperationService
from serviceflow.application.orchestration_service import OrchestrationService
from serviceflow.application.order_service import OrderService
from serviceflow.domain.models import IssueType, RequestedAction, TicketKind
from serviceflow.domain.policies import evaluate_policy
from serviceflow.infrastructure.answerability import AnswerabilityGate
from serviceflow.infrastructure.authorization import Authorization, Principal
from serviceflow.infrastructure.handoff import HandoffService
from serviceflow.infrastructure.qdrant_policy_store import PolicyRetriever


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    user_id: str
    tenant_id: str
    scene: str = "after_sales"
    confirmed: bool = False
    approval_granted: bool = False
    roles: tuple[str, ...] = ("customer",)
    session_id: str | None = None
    case_id: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool_call_id: str
    tool_name: str
    ok: bool
    code: str
    data: dict[str, object]
    retryable: bool = False

    def as_message(self) -> dict[str, object]:
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "content": _json_content(
                {"ok": self.ok, "code": self.code, "data": self.data, "retryable": self.retryable}
            ),
        }


class ToolExecutor:
    def __init__(
        self,
        session: AsyncSession,
        tenant_id: str,
        registry: ToolRegistry | None = None,
        policy_retriever: PolicyRetriever | None = None,
    ) -> None:
        self._session = session
        self._registry = registry or ToolRegistry.default()
        self._service = CaseService(session)
        self._orders = OrderService(session)
        self._policy_retriever = policy_retriever
        self._tenant_id = tenant_id

    async def execute(
        self,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> ToolResult:
        try:
            definition = self._registry.get(name)
        except KeyError:
            return self._result(call_id, name, False, "unauthorized", {})
        if context.scene not in definition.allowed_scene:
            return self._result(call_id, name, False, "unauthorized", {})
        principal = Principal(context.user_id, context.tenant_id, context.roles)
        authorization = Authorization(self._tenant_id)
        if not authorization.tenant_allowed(principal):
            return self._result(call_id, name, False, "unauthorized", {})
        if any(not isinstance(key, str) for key in arguments):
            return self._result(call_id, name, False, "validation_error", {})
        try:
            self._validate_arguments(definition, arguments)
        except ValueError:
            return self._result(call_id, name, False, "validation_error", {})
        order_id = _text(arguments.get("order_id"))
        if order_id is not None:
            order = await self._orders.get_order(order_id)
            allowed = order is not None and authorization.order_allowed(principal, order)
            gate = AnswerabilityGate.order(
                order_exists=order is not None,
                authorized=allowed,
            )
            if gate.code != "answerable":
                return self._result(call_id, name, False, gate.code, {})
        if definition.side_effect and definition.requires_confirmation and not context.confirmed:
            return self._result(call_id, name, False, "confirmation_required", {})
        if (
            name in {"request_refund", "create_compensation_request"}
            and not context.approval_granted
        ):
            if order_id is None:
                return self._result(call_id, name, False, "validation_error", {})
            order = await self._service.get_order(order_id)
            if order is not None and order.total_amount > Decimal("500.00"):
                return self._result(call_id, name, False, "approval_required", {})
        return await self._dispatch(call_id, name, arguments, context)

    async def _dispatch(
        self,
        call_id: str,
        name: str,
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> ToolResult:
        order_id = _text(arguments.get("order_id"))
        if name == "get_order" and order_id is not None:
            order = await self._service.get_order(order_id)
            return self._result(
                call_id,
                name,
                True,
                "ok",
                {"order_id": order.id, "order_status": order.status.value},
            )
        if name == "estimate_refund" and order_id is not None:
            order = await self._service.get_order(order_id)
            return self._result(
                call_id,
                name,
                True,
                "ok",
                {"order_id": order.id, "amount": str(order.total_amount)},
            )
        if name == "check_after_sales_eligibility" and order_id is not None:
            action = RequestedAction(str(arguments["requested_action"]))
            result = evaluate_policy(
                order=await self._service.get_order(order_id),
                requested_action=action,
                issue_type=IssueType.QUALITY,
                reference_date=date(2026, 8, 1),
            )
            return self._result(
                call_id,
                name,
                True,
                "ok",
                {"decision": result.decision.value, "policy_id": result.policy_id},
            )
        if name in {"create_return_request", "create_exchange_request"} and order_id is not None:
            kind = (
                TicketKind.EXCHANGE.value
                if name == "create_exchange_request"
                else TicketKind.SUPPORT.value
            )
            case = await self._service.create_ticket(
                order_id,
                kind=kind,
                summary=str(arguments.get("summary", name)),
            )
            data = {"case_id": case.case.id} if case.case else {}
            if case.order is not None:
                data["order_status"] = case.order.status.value
            return self._result(call_id, name, case.ok, case.code, data)
        if name == "request_refund" and order_id is not None:
            case = await self._service.request_refund(order_id)
            data = {"case_id": case.case.id} if case.case else {}
            if case.order is not None:
                data["order_status"] = case.order.status.value
            return self._result(call_id, name, case.ok, case.code, data)
        if name == "create_support_ticket" and order_id is not None:
            case = await self._service.create_ticket(
                order_id,
                kind=TicketKind.SUPPORT.value,
                summary=str(arguments["summary"]),
            )
            data = {"case_id": case.case.id} if case.case else {}
            if case.order is not None:
                data["order_status"] = case.order.status.value
            return self._result(call_id, name, case.ok, case.code, data)
        if name == "get_shipment" and order_id is not None:
            order = await self._service.get_order(order_id)
            return self._result(
                call_id,
                name,
                True,
                "ok",
                {"order_id": order.id, "shipment_status": order.status.value},
            )
        if name == "get_case":
            case_id = _text(arguments.get("case_id"))
            if case_id is not None:
                result = await self._service.get_case_status(case_id)
                if result is None or result.case is None:
                    return self._result(call_id, name, False, "not_found", {})
                return self._result(
                    call_id,
                    name,
                    True,
                    "ok",
                    {"case_id": case_id, "status": result.case.status.value},
                )
        if name == "search_policy_evidence" and self._policy_retriever is not None:
            query = _text(arguments.get("query"))
            if query is not None:
                evidence, backend, fallback = await self._policy_retriever.retrieve(
                    query,
                    tenant_id=context.tenant_id,
                    region="CN",
                    at=date(2026, 8, 1),
                    limit=5,
                )
                decision = AnswerabilityGate.policy(
                    evidence_count=len(evidence), has_conflict=False
                )
                handoff = await OrchestrationService(self._session).resolve(
                    decision,
                    principal=Principal(context.user_id, context.tenant_id, context.roles),
                    reason=f"政策检索无法形成可靠答案: {query}",
                    session_id=context.session_id,
                    case_id=context.case_id,
                    trace_id=context.trace_id,
                    context={"backend": backend, "fallback": fallback},
                )
                if handoff is not None:
                    return self._result(
                        call_id,
                        name,
                        False,
                        "handoff_created",
                        {"handoff_id": handoff.id, "reason_code": handoff.reason_code},
                    )
                return self._result(
                    call_id,
                    name,
                    True,
                    "ok",
                    {
                        "policy_ids": [item.document.policy_id for item in evidence],
                        "backend": backend,
                        "fallback": fallback,
                    },
                )
        if name == "search_policy_evidence":
            handoff = await HandoffService(self._session).create(
                principal=Principal(context.user_id, context.tenant_id, context.roles),
                reason_code="policy_evidence_unavailable",
                reason="政策检索服务当前不可用，无法形成可靠答案",
                session_id=context.session_id,
                case_id=context.case_id,
                trace_id=context.trace_id,
            )
            return self._result(
                call_id,
                name,
                False,
                "handoff_created",
                {"handoff_id": handoff.id, "reason_code": handoff.reason_code},
            )
        if name in {"get_operation_status", "poll_provider_operation"}:
            operation_id = _text(arguments.get("operation_id"))
            if operation_id is None:
                return self._result(call_id, name, False, "validation_error", {})
            lookup = await OperationService(self._session, tenant_id=self._tenant_id).get(
                operation_id, Principal(context.user_id, context.tenant_id, context.roles)
            )
            if lookup.operation is None:
                return self._result(call_id, name, False, lookup.code, {})
            provider = AnswerabilityGate.provider(lookup.operation.status.value)
            handoff = await OrchestrationService(self._session).resolve(
                provider,
                principal=Principal(context.user_id, context.tenant_id, context.roles),
                reason="外部操作结果未知，需要人工对账，禁止直接重试",
                session_id=context.session_id,
                case_id=lookup.operation.case_id,
                trace_id=context.trace_id,
                context={"operation_id": operation_id},
            )
            if handoff is not None:
                return self._result(
                    call_id,
                    name,
                    False,
                    "handoff_created",
                    {"handoff_id": handoff.id, "operation_status": "unknown"},
                )
            return self._result(
                call_id,
                name,
                True,
                "ok",
                {"operation_id": operation_id, "operation_status": lookup.operation.status.value},
            )
        if name == "create_compensation_request" and order_id is not None:
            case = await self._service.request_compensation(order_id)
            data = {"case_id": case.case.id} if case.case else {}
            return self._result(call_id, name, case.ok, case.code, data)
        if name == "request_handoff":
            handoff = await HandoffService(self._session).create(
                principal=Principal(context.user_id, context.tenant_id, context.roles),
                reason_code="user_requested",
                reason=str(arguments["reason"]),
                session_id=context.session_id,
                case_id=context.case_id,
                trace_id=context.trace_id,
            )
            return self._result(
                call_id,
                name,
                False,
                "handoff_created",
                {"handoff_id": handoff.id, "queue": handoff.queue},
            )
        return self._result(call_id, name, False, "validation_error", {})

    @staticmethod
    def _validate_arguments(definition: ToolDefinition, arguments: dict[str, object]) -> None:
        required = definition.parameters["required"]
        if not isinstance(required, list) or any(key not in arguments for key in required):
            raise ValueError("missing required argument")
        properties = definition.parameters["properties"]
        if not isinstance(properties, dict) or any(key not in properties for key in arguments):
            raise ValueError("unknown argument")
        for value in arguments.values():
            if not isinstance(value, str) or not value.strip():
                raise ValueError("arguments must be non-empty strings")

    @staticmethod
    def _result(
        call_id: str,
        name: str,
        ok: bool,
        code: str,
        data: dict[str, object],
    ) -> ToolResult:
        return ToolResult(call_id, name, ok, code, data, retryable=code in {"provider_transient"})


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _json_content(value: dict[str, object]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
