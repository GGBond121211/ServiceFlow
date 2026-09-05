from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.infrastructure.answerability import AnswerabilityAction, AnswerabilityDecision
from serviceflow.infrastructure.authorization import Principal
from serviceflow.infrastructure.handoff import HandoffService
from serviceflow.infrastructure.support_queue import HandoffRecord


class OrchestrationService:
    def __init__(self, session: AsyncSession) -> None:
        self._handoff = HandoffService(session)

    async def resolve(
        self,
        decision: AnswerabilityDecision,
        *,
        principal: Principal,
        reason: str,
        session_id: str | None,
        case_id: str | None,
        trace_id: str | None,
        context: dict[str, object] | None = None,
    ) -> HandoffRecord | None:
        if decision.action is not AnswerabilityAction.HANDOFF:
            return None
        return await self._handoff.create(
            principal=principal,
            reason_code=decision.code,
            reason=reason,
            session_id=session_id,
            case_id=case_id,
            trace_id=trace_id,
            context=context,
        )
