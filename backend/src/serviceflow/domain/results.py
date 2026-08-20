from dataclasses import dataclass
from enum import StrEnum


class Decision(StrEnum):
    ASK_FOR_INFO = "ask_for_info"
    EXPLAIN_ONLY = "explain_only"
    CANCEL = "cancel"
    DIRECT_REFUND = "direct_refund"
    APPROVAL_REQUIRED = "approval_required"
    CREATE_EXCHANGE_TICKET = "create_exchange_ticket"
    CREATE_SUPPORT_TICKET = "create_support_ticket"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    policy_id: str
    decision: Decision
    reason: str
