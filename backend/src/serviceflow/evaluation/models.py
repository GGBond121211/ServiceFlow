from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from serviceflow.domain.models import (
    ApprovalStatus,
    IssueType,
    OrderStatus,
    RefundStatus,
    RequestedAction,
    TicketStatus,
)
from serviceflow.domain.results import Decision


class EvalCategory(StrEnum):
    NORMAL_HANDLING = "normal_handling"
    BUSINESS_BOUNDARY = "business_boundary"
    CLARIFICATION = "clarification"
    NATURAL_LANGUAGE_VARIANT = "natural_language_variant"
    BLENDED_INTENT = "blended_intent"
    IMPLICIT_INTENT = "implicit_intent"
    NOISY_CONTEXT = "noisy_context"
    CORRECTION_NEGATION = "correction_negation"
    MULTI_TURN_STATE = "multi_turn_state"
    AMBIGUOUS_REQUEST = "ambiguous_request"


class EvalInitialState(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: str | None
    status: OrderStatus | None
    total_amount: Decimal | None
    delivered_days_ago: int | None


class EvalFinalState(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_status: OrderStatus | None = None
    refund_status: RefundStatus | None = None
    approval_status: ApprovalStatus | None = None
    ticket_status: TicketStatus | None = None


class EvalExpected(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent: RequestedAction | None
    issue_type: IssueType | None
    policy_id: str
    decision: Decision
    expected_tools: tuple[str, ...]
    final_state: EvalFinalState


class EvalCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    category: EvalCategory
    user_id: str
    initial_state: EvalInitialState
    messages: tuple[str, ...]
    approval_decision: bool | None = None
    expected: EvalExpected
