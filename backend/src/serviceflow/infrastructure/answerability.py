from dataclasses import dataclass
from enum import StrEnum


class AnswerabilityAction(StrEnum):
    PROCEED = "proceed"
    ASK_USER = "ask_user"
    QUERY_STATUS = "query_status"
    HANDOFF = "handoff"
    REFUSE = "refuse"


@dataclass(frozen=True, slots=True)
class AnswerabilityDecision:
    action: AnswerabilityAction
    code: str


class AnswerabilityGate:
    @staticmethod
    def order(*, order_exists: bool, authorized: bool) -> AnswerabilityDecision:
        if not order_exists:
            return AnswerabilityDecision(AnswerabilityAction.ASK_USER, "not_found")
        if not authorized:
            return AnswerabilityDecision(AnswerabilityAction.REFUSE, "unauthorized")
        return AnswerabilityDecision(AnswerabilityAction.PROCEED, "answerable")

    @staticmethod
    def policy(*, evidence_count: int, has_conflict: bool) -> AnswerabilityDecision:
        if has_conflict:
            return AnswerabilityDecision(AnswerabilityAction.HANDOFF, "policy_evidence_conflict")
        if evidence_count == 0:
            return AnswerabilityDecision(
                AnswerabilityAction.HANDOFF, "policy_evidence_insufficient"
            )
        return AnswerabilityDecision(AnswerabilityAction.PROCEED, "answerable")

    @staticmethod
    def provider(status: str) -> AnswerabilityDecision:
        if status == "pending":
            return AnswerabilityDecision(AnswerabilityAction.QUERY_STATUS, "provider_pending")
        if status == "unknown":
            return AnswerabilityDecision(AnswerabilityAction.HANDOFF, "provider_unknown")
        return AnswerabilityDecision(AnswerabilityAction.PROCEED, "answerable")
