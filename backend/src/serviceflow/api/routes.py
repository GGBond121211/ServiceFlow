from collections.abc import Mapping
from typing import cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from serviceflow.agent.graph import DEMO_REFERENCE_DATE, build_service_graph
from serviceflow.agent.model import OpenAICompatibleModel
from serviceflow.api.dependencies import get_session
from serviceflow.api.schemas import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    CaseResponse,
    CaseSummaryResponse,
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
from serviceflow.domain.models import Approval, Order, Refund, Ticket
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.seed import seed_database
from serviceflow.infrastructure.tables import OrderRow, UserRow

router = APIRouter(prefix="/api/v1")


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: str, session: Session = Depends(get_session)) -> OrderResponse:
    order = OrderService(session).get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    return _order_response(order)


@router.post("/demo/reset", response_model=ResetResponse)
def reset_demo(session: Session = Depends(get_session)) -> ResetResponse:
    Base.metadata.create_all(session.get_bind())
    seed_database(session)
    user_count = session.scalar(select(func.count()).select_from(UserRow))
    if user_count is None:
        user_count = 0
    order_count = session.scalar(select(func.count()).select_from(OrderRow))
    if order_count is None:
        order_count = 0
    return ResetResponse(users=user_count, orders=order_count)


@router.get("/cases/{case_id}", response_model=CaseResponse)
def get_case(case_id: str, session: Session = Depends(get_session)) -> CaseResponse:
    result = CaseService(session).get_case_status(case_id)
    if result is None or result.case is None:
        raise HTTPException(status_code=404, detail="case_not_found")
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
def create_conversation(
    payload: ConversationCreateRequest,
    request: Request,
) -> ConversationResponse:
    thread_id = f"demo-{uuid4().hex[:12]}"
    _conversations(request)[thread_id] = payload.user_id
    return _conversation_response(thread_id, {})


@router.post("/conversations/{thread_id}/messages", response_model=ConversationResponse)
def send_conversation_message(
    thread_id: str,
    payload: ConversationMessageRequest,
    request: Request,
) -> ConversationResponse:
    user_id = _conversation_user(request, thread_id)
    graph = _agent_graph(request)
    state = graph.invoke(
        {
            "thread_id": thread_id,
            "user_id": user_id,
            "user_message": payload.message,
            "reference_date": DEMO_REFERENCE_DATE,
        },
        config=_thread_config(thread_id),
    )
    return _conversation_response(thread_id, state)


@router.get("/conversations/{thread_id}", response_model=ConversationResponse)
def get_conversation(thread_id: str, request: Request) -> ConversationResponse:
    _conversation_user(request, thread_id)
    graph = request.app.state.agent_graph
    if graph is None:
        return _conversation_response(thread_id, {})
    state = graph.get_state(_thread_config(thread_id)).values
    return _conversation_response(thread_id, state)


@router.post(
    "/conversations/{thread_id}/approvals/{approval_id}",
    response_model=ConversationResponse,
)
def decide_conversation_approval(
    thread_id: str,
    approval_id: str,
    payload: ApprovalDecisionRequest,
    request: Request,
) -> ConversationResponse:
    _conversation_user(request, thread_id)
    graph = _agent_graph(request)
    state = graph.get_state(_thread_config(thread_id)).values
    if state.get("approval_id") != approval_id:
        raise HTTPException(status_code=404, detail="approval_not_found")
    resumed = graph.invoke(
        Command(resume={"approved": payload.approved}),
        config=_thread_config(thread_id),
    )
    return _conversation_response(thread_id, resumed)


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


def _case_type(case: Refund | Ticket | Approval) -> str:
    if isinstance(case, Refund):
        return "refund"
    if isinstance(case, Ticket):
        return "ticket"
    return "approval"


def _conversations(request: Request) -> dict[str, str]:
    return cast(dict[str, str], request.app.state.conversations)


def _conversation_user(request: Request, thread_id: str) -> str:
    user_id = _conversations(request).get(thread_id)
    if user_id is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    return user_id


def _agent_graph(request: Request) -> CompiledStateGraph:
    graph = request.app.state.agent_graph
    if graph is None:
        model = request.app.state.agent_model
        if model is None:
            model = OpenAICompatibleModel.from_env()
        graph = build_service_graph(
            model=model,
            session_factory=request.app.state.agent_session_factory,
            checkpointer=InMemorySaver(),
        )
        request.app.state.agent_graph = graph
    return cast(CompiledStateGraph, graph)


def _thread_config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


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
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
