from datetime import date, datetime
from decimal import Decimal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy.orm import Session, sessionmaker

from serviceflow.agent.intent import IntentExtractor
from serviceflow.agent.model import StructuredModel
from serviceflow.agent.state import AgentState, ToolEvent
from serviceflow.agent.tools import ServiceTools
from serviceflow.application.results import CaseResult
from serviceflow.domain.models import (
    Approval,
    IssueType,
    Order,
    OrderStatus,
    Refund,
    RequestedAction,
    Ticket,
    TicketKind,
)
from serviceflow.domain.policies import evaluate_policy
from serviceflow.domain.results import Decision

DEMO_REFERENCE_DATE = "2026-08-01"


class ServiceGraphNodes:
    def __init__(
        self,
        *,
        model: StructuredModel,
        session_factory: sessionmaker[Session],
    ) -> None:
        self._extractor = IntentExtractor(model)
        self._session_factory = session_factory

    def extract_intent(self, state: AgentState) -> AgentState:
        result = self._extractor.extract(state["user_message"])
        token_usage = state.get("token_usage", {"input": 0, "output": 0})
        updates: AgentState = {
            "error": result.error,
            "model_name": result.model_name,
            "prompt_version": result.prompt_version,
            "token_usage": {
                "input": token_usage["input"] + result.input_tokens,
                "output": token_usage["output"] + result.output_tokens,
            },
            "tool_events": state.get("tool_events", []),
        }
        if result.intent is None:
            return updates

        previous_issue = state.get("issue_type")
        issue_type = result.intent.issue_type
        if issue_type is IssueType.NONE and previous_issue not in (None, IssueType.NONE):
            issue_type = previous_issue
        order_id = result.intent.order_id
        if order_id is None:
            order_id = state.get("order_id")
        action = result.intent.requested_action
        if action is None:
            action = state.get("requested_action")
        missing_fields = []
        if order_id is None:
            missing_fields.append("order_id")
        if action is None:
            missing_fields.append("requested_action")
        updates.update(
            {
                "order_id": order_id,
                "requested_action": action,
                "issue_type": issue_type,
                "issue_summary": result.intent.issue_summary,
                "missing_fields": missing_fields,
            }
        )
        return updates

    def route_missing_info(self, state: AgentState) -> AgentState:
        if state.get("error") == "intent_parse_error":
            return {"policy_id": "POL-INFO-01", "decision": Decision.ASK_FOR_INFO}
        if state.get("missing_fields"):
            return {"policy_id": "POL-INFO-01", "decision": Decision.ASK_FOR_INFO}
        return {}

    def load_order(self, state: AgentState) -> AgentState:
        order_id = state.get("order_id")
        if order_id is None:
            return {"error": "missing_order_id"}
        with self._session_factory() as session:
            order = ServiceTools(session).get_order(order_id)
        event_code = "order_not_found"
        if order is not None:
            event_code = "ok"
        event = _tool_event("get_order", order is not None, event_code)
        events = [*state.get("tool_events", []), event]
        if order is None:
            return {"error": "order_not_found", "order_snapshot": None, "tool_events": events}
        return {"error": None, "order_snapshot": _order_snapshot(order), "tool_events": events}

    def evaluate_policy(self, state: AgentState) -> AgentState:
        order = _order_from_snapshot(state["order_snapshot"])
        result = evaluate_policy(
            order=order,
            requested_action=state.get("requested_action"),
            issue_type=state.get("issue_type"),
            reference_date=date.fromisoformat(state.get("reference_date", DEMO_REFERENCE_DATE)),
        )
        return {"policy_id": result.policy_id, "decision": result.decision}

    def execute_action(self, state: AgentState) -> AgentState:
        decision = state["decision"]
        order_id = state.get("order_id")
        if order_id is None or decision is Decision.EXPLAIN_ONLY:
            return {}
        with self._session_factory() as session:
            tools = ServiceTools(session)
            result, tool_name = _execute_decision(tools, state, order_id)
        if result is None:
            return {}
        case_id = None
        if result.case is not None:
            case_id = result.case.id
        event = _tool_event(tool_name, result.ok, result.code, case_id)
        error = None
        if not result.ok:
            error = result.code
        updates: AgentState = {
            "tool_events": [*state.get("tool_events", []), event],
            "case_id": case_id,
            "error": error,
        }
        if isinstance(result.case, Approval):
            updates["approval_id"] = result.case.id
        return updates

    def read_final_state(self, state: AgentState) -> AgentState:
        final: dict[str, object] = {}
        with self._session_factory() as session:
            tools = ServiceTools(session)
            order_id = state.get("order_id")
            order = None
            if order_id:
                order = tools.get_order(order_id)
            if order is not None:
                final["order_status"] = order.status.value
            case_id = state.get("case_id")
            case_result = None
            if case_id:
                case_result = tools.get_case_status(case_id)
            approval_id = state.get("approval_id")
            approval_result = None
            if approval_id:
                approval_result = tools.get_case_status(approval_id)
        if case_result and case_result.case:
            case = case_result.case
            if isinstance(case, Refund):
                final["refund_status"] = case.status.value
            elif isinstance(case, Ticket):
                final["ticket_status"] = case.status.value
            elif isinstance(case, Approval):
                final["approval_status"] = case.status.value
        if approval_result and isinstance(approval_result.case, Approval):
            final["approval_status"] = approval_result.case.status.value
        return {"final_business_state": final}

    def wait_for_approval(self, state: AgentState) -> AgentState:
        approval_id = state.get("approval_id")
        if approval_id is None:
            return {"error": "case_not_found"}
        answer = interrupt(
            {
                "approval_id": approval_id,
                "order_id": state.get("order_id"),
                "action": "approve_or_reject",
            }
        )
        approved = bool(answer["approved"])
        with self._session_factory() as session:
            result = ServiceTools(session).decide_approval(approval_id, approved=approved)
        case_id = approval_id
        if result.case is not None:
            case_id = result.case.id
        event = _tool_event("decide_approval", result.ok, result.code, case_id)
        error = None
        if not result.ok:
            error = result.code
        return {
            "case_id": case_id,
            "error": error,
            "tool_events": [*state.get("tool_events", []), event],
        }

    def compose_response(self, state: AgentState) -> AgentState:
        error = state.get("error")
        if error == "intent_parse_error":
            message = "我没有理解这条请求，请提供订单号和要办理的事项。"
        elif state.get("missing_fields"):
            labels = _missing_field_labels(state["missing_fields"])
            message = f"请补充以下信息：{', '.join(labels)}。"
        elif error == "order_not_found":
            message = f"订单 {state.get('order_id')} 不存在。"
        elif error:
            message = f"这条请求未能完成：{error}。"
        else:
            message = _success_message(state)
        return {"assistant_message": message}


def build_service_graph(
    *,
    model: StructuredModel,
    session_factory: sessionmaker[Session],
    checkpointer: BaseCheckpointSaver | None = None,
):
    nodes = ServiceGraphNodes(model=model, session_factory=session_factory)
    builder = StateGraph(AgentState)
    builder.add_node("extract_intent", nodes.extract_intent)
    builder.add_node("route_missing_info", nodes.route_missing_info)
    builder.add_node("load_order", nodes.load_order)
    builder.add_node("evaluate_policy", nodes.evaluate_policy)
    builder.add_node("execute_action", nodes.execute_action)
    builder.add_node("read_final_state", nodes.read_final_state)
    builder.add_node("wait_for_approval", nodes.wait_for_approval)
    builder.add_node("compose_response", nodes.compose_response)
    builder.add_edge(START, "extract_intent")
    builder.add_edge("extract_intent", "route_missing_info")
    builder.add_conditional_edges(
        "route_missing_info",
        _route_after_intent,
        {"load_order": "load_order", "compose_response": "compose_response"},
    )
    builder.add_conditional_edges(
        "load_order",
        _route_after_order,
        {"evaluate_policy": "evaluate_policy", "compose_response": "compose_response"},
    )
    builder.add_edge("evaluate_policy", "execute_action")
    builder.add_edge("execute_action", "read_final_state")
    builder.add_conditional_edges(
        "read_final_state",
        _route_after_final_state,
        {"wait_for_approval": "wait_for_approval", "compose_response": "compose_response"},
    )
    builder.add_edge("wait_for_approval", "read_final_state")
    builder.add_edge("compose_response", END)
    return builder.compile(checkpointer=checkpointer)


def _route_after_intent(state: AgentState) -> str:
    has_error = bool(state.get("error"))
    has_missing_fields = bool(state.get("missing_fields"))
    if has_error or has_missing_fields:
        return "compose_response"
    return "load_order"


def _route_after_order(state: AgentState) -> str:
    if state.get("error"):
        return "compose_response"
    return "evaluate_policy"


def _route_after_final_state(state: AgentState) -> str:
    final = state.get("final_business_state", {})
    if (
        state.get("decision") is Decision.APPROVAL_REQUIRED
        and final.get("approval_status") == "pending"
    ):
        return "wait_for_approval"
    return "compose_response"


def _execute_decision(
    tools: ServiceTools,
    state: AgentState,
    order_id: str,
) -> tuple[CaseResult | None, str]:
    decision = state["decision"]
    if decision is Decision.CANCEL:
        return tools.cancel_order(order_id), "cancel_order"
    if decision is Decision.DIRECT_REFUND:
        return tools.request_refund(order_id), "request_refund"
    if decision is Decision.APPROVAL_REQUIRED:
        return tools.create_approval(order_id, RequestedAction.REFUND), "create_approval"
    if decision is Decision.CREATE_EXCHANGE_TICKET:
        return (
            tools.create_ticket(
                order_id,
                kind=TicketKind.EXCHANGE.value,
                summary=state.get("issue_summary", "商品质量问题"),
            ),
            "create_ticket",
        )
    if decision is Decision.CREATE_SUPPORT_TICKET:
        return (
            tools.create_ticket(
                order_id,
                kind=TicketKind.SUPPORT.value,
                summary=state.get("issue_summary", "售后支持请求"),
            ),
            "create_ticket",
        )
    return None, ""


def _order_snapshot(order: Order) -> dict[str, object]:
    delivered_at = None
    if order.delivered_at is not None:
        delivered_at = order.delivered_at.isoformat()
    return {
        "id": order.id,
        "user_id": order.user_id,
        "status": order.status.value,
        "total_amount": str(order.total_amount),
        "placed_at": order.placed_at.isoformat(),
        "delivered_at": delivered_at,
    }


def _order_from_snapshot(snapshot: dict[str, object] | None) -> Order | None:
    if snapshot is None:
        return None
    delivered_at = snapshot.get("delivered_at")
    parsed_delivered_at = None
    if delivered_at:
        parsed_delivered_at = datetime.fromisoformat(str(delivered_at))
    return Order(
        id=str(snapshot["id"]),
        user_id=str(snapshot["user_id"]),
        status=OrderStatus(str(snapshot["status"])),
        total_amount=Decimal(str(snapshot["total_amount"])),
        placed_at=datetime.fromisoformat(str(snapshot["placed_at"])),
        delivered_at=parsed_delivered_at,
    )


def _tool_event(
    tool: str,
    ok: bool,
    code: str,
    case_id: str | None = None,
) -> ToolEvent:
    return {"tool": tool, "ok": ok, "code": code, "case_id": case_id}


def _success_message(state: AgentState) -> str:
    order_id = state.get("order_id")
    decision = state.get("decision")
    final = state.get("final_business_state", {})
    if decision is Decision.EXPLAIN_ONLY:
        return f"订单 {order_id} 当前状态为 {final.get('order_status')}。"
    if decision is Decision.APPROVAL_REQUIRED:
        approval_status = final.get("approval_status")
        if approval_status == "approved":
            return f"订单 {order_id} 已审批通过，退款已完成。"
        if approval_status == "rejected":
            return f"订单 {order_id} 的退款审批未通过。"
        return f"订单 {order_id} 需要审批，审批编号为 {state.get('approval_id')}。"
    return f"订单 {order_id} 已处理，最终状态为 {final.get('order_status')}。"


def _missing_field_labels(fields: list[str]) -> list[str]:
    labels = []
    for field in fields:
        if field == "order_id":
            labels.append("订单号（order_id）")
        elif field == "requested_action":
            labels.append("处理事项（requested_action）")
        else:
            labels.append(field)
    return labels
