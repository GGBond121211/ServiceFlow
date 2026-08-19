from typing import TypedDict

from serviceflow.domain.models import IssueType, RequestedAction
from serviceflow.domain.results import Decision


class ToolEvent(TypedDict):
    tool: str
    ok: bool
    code: str
    case_id: str | None


class AgentState(TypedDict, total=False):
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
