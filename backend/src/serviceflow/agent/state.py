from typing import NotRequired, TypedDict

from serviceflow.domain.models import IssueType, RequestedAction
from serviceflow.domain.results import Decision


class ToolEvent(TypedDict):
    tool: str
    ok: bool
    code: str
    case_id: str | None
    role: NotRequired[str]


class AgentState(TypedDict, total=False):
    # --- 2.0 Step 2 新增的关联 ID ---
    # `total=False`，所以 V1 的调用方不传这些键仍然合法，八节点图行为不变。
    # 加进来是为了让 API 响应、数据库行、checkpoint 和事件日志能互相关联
    # （Step 2 验收第 3 条）。`case_id` 已存在但语义是 V1 的"业务结果 id"
    # （REFUND-xxx / TICKET-xxx），所以案件用 `after_sales_case_id` 另起一个名，
    # 避免两种 id 混用。
    session_id: str
    goal_id: str
    after_sales_case_id: str
    operation_id: str
    run_id: str
    tenant_id: str
    case_state_version: int
    thread_id: str
    user_id: str
    user_message: str
    reference_date: str
    order_id: str | None
    requested_action: RequestedAction | None
    issue_type: IssueType
    issue_summary: str
    missing_fields: list[str]
    order_snapshot: dict[str, object] | None
    policy_id: str
    decision: Decision
    tool_events: list[ToolEvent]
    approval_id: str | None
    case_id: str | None
    final_business_state: dict[str, object]
    assistant_message: str
    error: str | None
    model_name: str
    prompt_version: str
    token_usage: dict[str, int]
    confirmed_memories: list[dict[str, object]]
    prompt_run_id: str
    context_sections: list[str]
    context_dropped_sections: list[str]
    context_tokens: int
    policy_evidence: list[dict[str, object]]
    policy_retrieval_backend: str | None
    policy_retrieval_fallback: str | None
    agent_status: str
    confirmed: bool
    approval_granted: bool
    pending_tool_call: dict[str, object] | None
    pending_code: str | None
