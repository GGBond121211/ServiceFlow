import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter
from typing import cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from serviceflow.agent.graph import DEMO_REFERENCE_DATE, build_service_graph
from serviceflow.agent.model import OpenAICompatibleModel
from serviceflow.api.dependencies import get_session
from serviceflow.api.schemas import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    CaseResponse,
    CaseSummaryResponse,
    ConfirmationRequest,
    ConversationCreateRequest,
    ConversationMessageRequest,
    ConversationResponse,
    HealthResponse,
    OrderItemResponse,
    OrderResponse,
    ResetResponse,
    TokenUsageResponse,
    ToolEventResponse,
)
from serviceflow.application.case_service import CaseService
from serviceflow.application.order_service import OrderService
from serviceflow.application.session_service import SessionService
from serviceflow.domain.models import Approval, Order, Refund, RequestedAction, Ticket
from serviceflow.domain.sessions import Channel, ConversationSession
from serviceflow.infrastructure.approval_service import ApprovalService
from serviceflow.infrastructure.audit_store import GatewayAuditWriter
from serviceflow.infrastructure.authorization import Principal
from serviceflow.infrastructure.checkpoint_store import SqlAlchemyCheckpointSaver
from serviceflow.infrastructure.database import ensure_database_schema
from serviceflow.infrastructure.gateway_context import bind_gateway_context
from serviceflow.infrastructure.model_gateway import build_model_gateway_from_env
from serviceflow.infrastructure.seed import seed_database
from serviceflow.infrastructure.tables import ConfirmationClaimRow, OrderRow, UserRow
from serviceflow.infrastructure.timing import add_timing, measure_timing
from serviceflow.infrastructure.tool_executor import ToolExecutor
from serviceflow.mcp.client import MCPClient
from serviceflow.mcp.host import MCPHost
from serviceflow.mcp.server import MCPServer
from serviceflow.mcp.stdio_client import StdioMCPClient

router = APIRouter(prefix="/api/v1")


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> OrderResponse:
    order = await OrderService(session).get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    _require_demo_user(request, order.user_id)
    return _order_response(order)


@router.post("/demo/reset", response_model=ResetResponse)
async def reset_demo(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ResetResponse:
    if request.headers.get("X-ServiceFlow-Demo-Role") != "operator":
        raise HTTPException(status_code=403, detail="demo_operator_required")
    await session.run_sync(_ensure_session_schema)
    await seed_database(session)
    user_count = await session.scalar(select(func.count()).select_from(UserRow))
    if user_count is None:
        user_count = 0
    order_count = await session.scalar(select(func.count()).select_from(OrderRow))
    if order_count is None:
        order_count = 0
    return ResetResponse(users=user_count, orders=order_count)


@router.get("/cases/{case_id}", response_model=CaseResponse)
async def get_case(
    case_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> CaseResponse:
    result = await CaseService(session).get_case_status(case_id)
    if result is None or result.case is None:
        raise HTTPException(status_code=404, detail="case_not_found")
    if result.order is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    _require_demo_user(request, result.order.user_id)
    order = None
    if result.order is not None:
        order = _order_response(result.order)
    return CaseResponse(
        code=result.code,
        order=order,
        case=CaseSummaryResponse(
            id=result.case.id,
            type=_case_type(result.case),
            status=result.case.status.value,
        ),
    )


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    payload: ConversationCreateRequest,
    request: Request,
) -> ConversationResponse:
    _require_demo_user(request, payload.user_id)
    thread_id = f"demo-{uuid4().hex[:12]}"
    await SessionService(request.app.state.agent_session_factory).start_session(
        tenant_id="default",
        user_id=payload.user_id,
        channel=Channel.WEB,
        session_id=thread_id,
    )
    return _timed_conversation_response(thread_id, {})


@router.post("/conversations/{thread_id}/messages", response_model=ConversationResponse)
async def send_conversation_message(
    thread_id: str,
    payload: ConversationMessageRequest,
    request: Request,
) -> ConversationResponse:
    conversation = await _conversation_session(request, thread_id)
    user_id = conversation.user_id
    graph = _agent_graph(request)
    previous = await graph.aget_state(_thread_config(thread_id))
    if previous.values.get("agent_status") in {"WAITING_CONFIRMATION", "WAITING_APPROVAL"}:
        raise HTTPException(status_code=409, detail="pending_action_requires_resolution")
    run_id = f"RUN-{uuid4().hex[:12].upper()}"
    with measure_timing("graph_ms"):
        with bind_gateway_context(
            tenant_id=conversation.tenant_id,
            request_id=f"REQ-{uuid4().hex[:12].upper()}",
            session_id=thread_id,
            run_id=run_id,
        ):
            state = await graph.ainvoke(
                {
                    "thread_id": thread_id,
                    "session_id": thread_id,
                    "tenant_id": conversation.tenant_id,
                    "run_id": run_id,
                    "user_id": user_id,
                    "user_message": payload.message,
                    "reference_date": DEMO_REFERENCE_DATE,
                },
                config=_thread_config(thread_id),
            )
    return _timed_conversation_response(thread_id, state)


@router.get("/conversations/{thread_id}", response_model=ConversationResponse)
async def get_conversation(thread_id: str, request: Request) -> ConversationResponse:
    await _conversation_user(request, thread_id)
    graph = _agent_graph(request)
    with measure_timing("graph_state_ms"):
        state = (await graph.aget_state(_thread_config(thread_id))).values
    return _timed_conversation_response(thread_id, state)


@router.post(
    "/conversations/{thread_id}/approvals/{approval_id}",
    response_model=ConversationResponse,
)
async def decide_conversation_approval(
    thread_id: str,
    approval_id: str,
    payload: ApprovalDecisionRequest,
    request: Request,
) -> ConversationResponse:
    user_id = await _conversation_user(request, thread_id)
    if request.headers.get("X-ServiceFlow-Demo-Role") != "approver":
        raise HTTPException(status_code=403, detail="demo_approver_required")
    graph = _agent_graph(request)
    with measure_timing("graph_state_ms"):
        state = (await graph.aget_state(_thread_config(thread_id))).values
    if state.get("approval_id") != approval_id:
        raise HTTPException(status_code=404, detail="approval_not_found")
    if state.get("agent_status") is not None and state.get("agent_status") != "WAITING_APPROVAL":
        raise HTTPException(status_code=409, detail="approval_not_pending")
    if state.get("agent_status") == "WAITING_APPROVAL":
        resumed = await _resume_native_approval(
            request, graph, state, payload.approved, subject_user_id=user_id
        )
        return _timed_conversation_response(thread_id, resumed)
    with measure_timing("graph_ms"):
        resumed = await graph.ainvoke(
            Command(resume={"approved": payload.approved}),
            config=_thread_config(thread_id),
        )
    return _timed_conversation_response(thread_id, resumed)


@router.post(
    "/conversations/{thread_id}/confirmations",
    response_model=ConversationResponse,
)
async def confirm_conversation_action(
    thread_id: str,
    payload: ConfirmationRequest,
    request: Request,
) -> ConversationResponse:
    user_id = await _conversation_user(request, thread_id)
    graph = _agent_graph(request)
    state = (await graph.aget_state(_thread_config(thread_id))).values
    pending = state.get("pending_tool_call")
    if state.get("agent_status") != "WAITING_CONFIRMATION" or not isinstance(pending, dict):
        raise HTTPException(status_code=409, detail="confirmation_not_pending")
    _validate_pending_binding(pending, user_id=user_id, tenant_id="default")
    canonical = json.dumps(pending, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    claim_id = sha256(f"{thread_id}:{canonical}".encode()).hexdigest()
    async with request.app.state.agent_session_factory() as session:
        session.add(ConfirmationClaimRow(
            id=claim_id, session_id=thread_id, claimed_at=datetime.now(UTC)
        ))
        try:
            await session.commit()
        except IntegrityError as error:
            await session.rollback()
            raise HTTPException(status_code=409, detail="confirmation_already_consumed") from error
    if not payload.confirmed:
        updates = {
            "agent_status": "CANCELLED",
            "pending_tool_call": None,
            "pending_code": None,
            "assistant_message": "已取消待确认操作，未执行。",
            "conversation_history": [
                *state.get("conversation_history", [])[-6:],
                {"role": "user", "content": "取消待确认操作"},
                {"role": "assistant", "content": "已取消，未执行。"},
            ],
        }
        await graph.aupdate_state(_thread_config(thread_id), updates)
        return _timed_conversation_response(thread_id, {**state, **updates})
    resumed = await _resume_native_confirmation(request, graph, state, pending)
    return _timed_conversation_response(thread_id, resumed)


def _order_response(order: Order) -> OrderResponse:
    delivered_at = None
    if order.delivered_at is not None:
        delivered_at = order.delivered_at.isoformat()
    items = []
    for item in order.items:
        items.append(
            OrderItemResponse(
                id=item.id,
                product_name=item.product_name,
                category=item.category,
                unit_price=str(item.unit_price),
                quantity=item.quantity,
            )
        )
    return OrderResponse(
        id=order.id,
        user_id=order.user_id,
        status=order.status.value,
        total_amount=str(order.total_amount),
        placed_at=order.placed_at.isoformat(),
        delivered_at=delivered_at,
        items=items,
    )


def _ensure_session_schema(session: Session) -> None:
    ensure_database_schema(session.connection())


def _case_type(case: Refund | Ticket | Approval) -> str:
    if isinstance(case, Refund):
        return "refund"
    if isinstance(case, Ticket):
        return "ticket"
    return "approval"


async def _conversation_user(request: Request, thread_id: str) -> str:
    return (await _conversation_session(request, thread_id)).user_id


def _require_demo_user(request: Request, user_id: str) -> None:
    if request.headers.get("X-ServiceFlow-User") != user_id:
        raise HTTPException(status_code=403, detail="demo_user_mismatch")


async def _conversation_session(
    request: Request, thread_id: str
) -> ConversationSession:
    session = await SessionService(request.app.state.agent_session_factory).load_session(thread_id)
    if session is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    _require_demo_user(request, session.user_id)
    return session


def _agent_graph(request: Request) -> CompiledStateGraph:
    graph = request.app.state.agent_graph
    if graph is None:
        model = request.app.state.agent_model
        if model is None:
            gateway_url = os.getenv("SERVICEFLOW_GATEWAY_URL")
            if gateway_url:
                model = OpenAICompatibleModel.for_gateway(
                    base_url=gateway_url,
                    model=os.getenv("SERVICEFLOW_MODEL", "deepseek-v4-flash"),
                )
            else:
                model = build_model_gateway_from_env(
                    telemetry=request.app.state.telemetry,
                    audit_sink=GatewayAuditWriter(
                        request.app.state.agent_session_factory
                    ),
                )
        graph = build_service_graph(
            model=model,
            session_factory=request.app.state.agent_session_factory,
            checkpointer=SqlAlchemyCheckpointSaver(
                request.app.state.agent_session_factory
            ),
            redis_store=request.app.state.redis_store,
            policy_retriever=request.app.state.policy_retriever,
            telemetry=request.app.state.telemetry,
        )
        request.app.state.agent_graph = graph
    return cast(CompiledStateGraph, graph)


def _thread_config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


async def _resume_native_confirmation(
    request: Request,
    graph: CompiledStateGraph,
    state: Mapping[str, object],
    pending: dict[str, object],
) -> Mapping[str, object]:
    result = await _call_native_pending(request, pending, confirmed=True, approval_granted=False)
    if result.get("code") == "approval_required":
        arguments = pending.get("arguments")
        order_id = arguments.get("order_id") if isinstance(arguments, dict) else None
        if not isinstance(order_id, str):
            raise HTTPException(status_code=422, detail="approval_order_missing")
        async with request.app.state.agent_session_factory() as session:
            approval = await CaseService(session).create_approval(
                order_id, _requested_action_for_tool(str(pending.get("name")))
            )
            final = await _read_native_final_state(session, result, pending)
        approval_id = approval.case.id if approval.case is not None else None
        if approval_id is None:
            raise HTTPException(status_code=500, detail="approval_create_failed")
        final["approval_status"] = "pending"
        updates = _native_state_updates(
            state,
            pending,
            result,
            final,
            status="WAITING_APPROVAL",
            assistant_message="这项操作需要人工审批，当前只创建申请，尚未执行。",
            approval_id=approval_id,
        )
    else:
        async with request.app.state.agent_session_factory() as session:
            final = await _read_native_final_state(session, result, pending)
        updates = _native_state_updates(
            state,
            pending,
            result,
            final,
            status="COMPLETED" if result.get("ok") else "MANUAL_REQUIRED",
            assistant_message=_native_result_message(result),
            approval_id=None,
        )
    await graph.aupdate_state(_thread_config(str(state["thread_id"])), updates)
    return {**state, **updates}


async def _resume_native_approval(
    request: Request,
    graph: CompiledStateGraph,
    state: Mapping[str, object],
    approved: bool,
    *,
    subject_user_id: str,
) -> Mapping[str, object]:
    approval_id = state.get("approval_id")
    if not isinstance(approval_id, str):
        raise HTTPException(status_code=404, detail="approval_not_found")
    pending = state.get("pending_tool_call")
    if not isinstance(pending, dict):
        raise HTTPException(status_code=422, detail="pending_tool_invalid")
    _validate_pending_binding(pending, user_id=subject_user_id, tenant_id="default")
    arguments = pending.get("arguments")
    order_id = arguments.get("order_id") if isinstance(arguments, dict) else None
    if not isinstance(order_id, str):
        raise HTTPException(status_code=422, detail="approval_order_missing")
    async with request.app.state.agent_session_factory() as session:
        result = await ApprovalService(session, tenant_id="default").decide(
            approval_id=approval_id,
            approved=approved,
            subject_user_id=subject_user_id,
            actor=Principal("serviceflow-demo-approver", "default", ("approver",)),
            expected_order_id=order_id,
            expected_action=_requested_action_for_tool(str(pending.get("name"))),
            session_id=str(state.get("session_id", state.get("thread_id", ""))) or None,
            trace_id=_optional_text(state.get("run_id")),
        )
        final: dict[str, object] = {}
        if result.order is not None:
            final["order_status"] = result.order.status.value
        approval = await CaseService(session).get_case_status(approval_id)
        if approval is not None and approval.case is not None:
            final["approval_status"] = getattr(
                approval.case.status, "value", approval.case.status
            )
        if result.case is not None and result.case.id != approval_id:
            result_status = getattr(result.case.status, "value", result.case.status)
            if isinstance(result.case, Refund):
                final["refund_status"] = result_status
            elif isinstance(result.case, Ticket):
                final["ticket_status"] = result_status
    event = {
        "tool": "decide_approval",
        "ok": result.ok,
        "code": result.code,
        "case_id": approval_id,
    }
    updates = {
        "tool_events": [*state.get("tool_events", []), event],
        "final_business_state": final,
        "agent_status": "COMPLETED" if result.ok else "MANUAL_REQUIRED",
        "assistant_message": (
            "申请已审批通过；处理结果以显示的数据库状态为准。"
            if approved and result.ok
            else "申请审批未通过。"
            if not approved and result.ok
            else "审批处理失败，请转人工继续。"
        ),
        "pending_tool_call": None,
        "pending_code": None,
    }
    updates["conversation_history"] = [
        *state.get("conversation_history", [])[-6:],
        {"role": "user", "content": "同意审批" if approved else "拒绝审批"},
        {"role": "assistant", "content": updates["assistant_message"]},
    ]
    await graph.aupdate_state(_thread_config(str(state["thread_id"])), updates)
    return {**state, **updates}


async def _call_native_pending(
    request: Request,
    pending: dict[str, object],
    *,
    confirmed: bool,
    approval_granted: bool,
) -> dict[str, object]:
    call_id = pending.get("call_id")
    name = pending.get("name")
    arguments = pending.get("arguments")
    if not isinstance(call_id, str) or not isinstance(name, str) or not isinstance(arguments, dict):
        raise HTTPException(status_code=422, detail="pending_tool_invalid")
    context = {
        "user_id": await _conversation_user(
            request, str(request.path_params["thread_id"])
        ),
        "tenant_id": "default",
        "confirmed": confirmed,
        "approval_granted": approval_granted,
        "session_id": str(request.path_params["thread_id"]),
        "reference_date": DEMO_REFERENCE_DATE,
    }
    if os.getenv("SERVICEFLOW_MCP_TRANSPORT", "in_process") == "stdio":
        client = StdioMCPClient((sys.executable, "-m", "serviceflow.mcp.stdio_server"))
        try:
            return await MCPHost(client).call_tool(
                call_id=call_id, name=name, arguments=arguments, context=context
            )
        finally:
            await client.close()
    async with request.app.state.agent_session_factory() as session:
        host = MCPHost(
            MCPClient(
                MCPServer(
                    ToolExecutor(
                        session,
                        policy_retriever=request.app.state.policy_retriever,
                        tenant_id="default",
                    )
                )
            )
        )
        return await host.call_tool(
            call_id=call_id, name=name, arguments=arguments, context=context
        )


async def _read_native_final_state(
    session: AsyncSession,
    result: Mapping[str, object],
    pending: Mapping[str, object],
) -> dict[str, object]:
    final: dict[str, object] = {}
    arguments = pending.get("arguments")
    order_id = arguments.get("order_id") if isinstance(arguments, dict) else None
    if isinstance(order_id, str):
        order = await CaseService(session).get_order(order_id)
        if order is not None:
            final["order_status"] = order.status.value
    data = result.get("data")
    case_id = data.get("case_id") if isinstance(data, dict) else None
    if isinstance(case_id, str):
        case = await CaseService(session).get_case_status(case_id)
        if case is not None and case.case is not None:
            final["case_status"] = getattr(case.case.status, "value", case.case.status)
    return final


def _native_state_updates(
    state: Mapping[str, object],
    pending: Mapping[str, object],
    result: Mapping[str, object],
    final: dict[str, object],
    *,
    status: str,
    assistant_message: str,
    approval_id: str | None,
) -> dict[str, object]:
    data = result.get("data")
    case_id = data.get("case_id") if isinstance(data, dict) else None
    event = {
        "tool": pending["name"],
        "ok": result.get("ok", False),
        "code": result.get("code", "unknown"),
        "case_id": case_id if isinstance(case_id, str) else None,
    }
    return {
        "tool_events": [*state.get("tool_events", []), event],
        "final_business_state": final,
        "agent_status": status,
        "assistant_message": assistant_message,
        "approval_id": approval_id,
        "pending_tool_call": dict(pending) if approval_id else None,
        "pending_code": result.get("code") if approval_id else None,
        "conversation_history": [
            *state.get("conversation_history", [])[-6:],
            {"role": "user", "content": "确认执行待处理操作"},
            {"role": "assistant", "content": assistant_message},
        ],
    }


def _native_result_message(result: Mapping[str, object]) -> str:
    if result.get("ok"):
        return "已完成这项售后操作，最终状态已从业务数据库回读。"
    return "工具未能完成这项操作，请转人工继续。"


def _validate_pending_binding(
    pending: Mapping[str, object],
    *,
    user_id: str,
    tenant_id: str,
) -> None:
    arguments = pending.get("arguments")
    if not isinstance(arguments, dict):
        raise HTTPException(status_code=422, detail="pending_tool_invalid")
    canonical = json.dumps(arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    if (
        pending.get("bound_user_id") != user_id
        or pending.get("bound_tenant_id") != tenant_id
        or pending.get("argument_digest") != sha256(canonical.encode("utf-8")).hexdigest()
    ):
        raise HTTPException(status_code=409, detail="pending_binding_mismatch")
    expires_at = pending.get("expires_at")
    if not isinstance(expires_at, str) or datetime.fromisoformat(expires_at) <= datetime.now(UTC):
        raise HTTPException(status_code=409, detail="pending_confirmation_expired")


def _requested_action_for_tool(tool_name: str) -> RequestedAction:
    if tool_name == "request_refund":
        return RequestedAction.REFUND
    if tool_name == "create_compensation_request":
        return RequestedAction.COMPENSATION
    raise HTTPException(status_code=422, detail="approval_action_invalid")


def _conversation_response(
    thread_id: str,
    state: Mapping[str, object],
) -> ConversationResponse:
    final_state = cast(dict[str, object], state.get("final_business_state", {}))
    approval_id = _optional_text(state.get("approval_id"))
    approval_status = _optional_text(final_state.get("approval_status"))
    approval = None
    if approval_id and approval_status:
        approval = ApprovalResponse(id=approval_id, status=approval_status)

    assistant_message = _optional_text(state.get("assistant_message"))
    if assistant_message is None:
        assistant_message = ""
    if not assistant_message and approval_status == "pending":
        assistant_message = f"订单需要审批后才能继续处理，审批编号为 {approval_id}。"

    events = cast(list[dict[str, object]], state.get("tool_events", []))
    token_usage = cast(dict[str, int], state.get("token_usage", {}))
    tool_events = []
    for event in events:
        tool_events.append(ToolEventResponse.model_validate(event))
    return ConversationResponse(
        thread_id=thread_id,
        assistant_message=assistant_message,
        decision=_optional_text(state.get("decision")),
        policy_id=_optional_text(state.get("policy_id")),
        tool_events=tool_events,
        final_business_state=final_state,
        approval=approval,
        model=_optional_text(state.get("model_name")),
        prompt_version=_optional_text(state.get("prompt_version")),
        token_usage=TokenUsageResponse.model_validate(token_usage),
        agent_status=_optional_text(state.get("agent_status")),
    )


def _timed_conversation_response(
    thread_id: str,
    state: Mapping[str, object],
) -> ConversationResponse:
    started_at = perf_counter()
    response = _conversation_response(thread_id, state)
    add_timing("response_build_ms", (perf_counter() - started_at) * 1000)
    return response


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
