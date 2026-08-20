from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class ResetResponse(BaseModel):
    users: int
    orders: int


class OrderItemResponse(BaseModel):
    id: str
    product_name: str
    category: str
    unit_price: str
    quantity: int


class OrderResponse(BaseModel):
    id: str
    user_id: str
    status: str
    total_amount: str
    placed_at: str
    delivered_at: str | None
    items: list[OrderItemResponse]


class CaseSummaryResponse(BaseModel):
    id: str
    type: str
    status: str


class CaseResponse(BaseModel):
    code: str
    order: OrderResponse | None
    case: CaseSummaryResponse


class ConversationCreateRequest(BaseModel):
    user_id: str


class ConversationMessageRequest(BaseModel):
    message: str


class ApprovalDecisionRequest(BaseModel):
    approved: bool


class ToolEventResponse(BaseModel):
    tool: str
    ok: bool
    code: str
    case_id: str | None


class ApprovalResponse(BaseModel):
    id: str
    status: str


class TokenUsageResponse(BaseModel):
    input: int = 0
    output: int = 0


class ConversationResponse(BaseModel):
    thread_id: str
    assistant_message: str
    decision: str | None
    policy_id: str | None
    tool_events: list[ToolEventResponse]
    final_business_state: dict[str, object]
    approval: ApprovalResponse | None
    model: str | None
    prompt_version: str | None
    token_usage: TokenUsageResponse
