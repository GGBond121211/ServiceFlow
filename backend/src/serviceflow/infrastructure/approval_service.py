from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.application.case_service import CaseService
from serviceflow.application.results import CaseResult
from serviceflow.domain.models import ApprovalStatus, RequestedAction
from serviceflow.infrastructure.authorization import Authorization, Principal
from serviceflow.infrastructure.event_log import EventLog


class ApprovalService:
    def __init__(self, session: AsyncSession, *, tenant_id: str) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._cases = CaseService(session)

    async def decide(
        self,
        *,
        approval_id: str,
        approved: bool,
        subject_user_id: str,
        actor: Principal,
        expected_order_id: str,
        expected_action: RequestedAction,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> CaseResult:
        authorization = Authorization(self._tenant_id)
        if not authorization.can_approve(actor):
            return CaseResult(ok=False, code="unauthorized")
        approval = await self._cases.get_case_status(approval_id)
        if approval is None or approval.case is None:
            return CaseResult(ok=False, code="case_not_found")
        order = approval.order
        if (
            order is None
            or order.id != expected_order_id
            or order.user_id != subject_user_id
        ):
            return CaseResult(ok=False, code="unauthorized")
        if approval.case.status is not ApprovalStatus.PENDING:
            return CaseResult(
                ok=False,
                code="approval_already_decided",
                order=order,
                case=approval.case,
            )
        if approval.case.requested_action is not expected_action:
            return CaseResult(ok=False, code="approval_binding_mismatch", order=order)
        result = await self._cases.decide_approval(approval_id, approved, commit=False)
        await EventLog(self._session).append(
            event_type="approval_decided",
            tenant_id=self._tenant_id,
            actor=actor.user_id,
            session_id=session_id,
            case_id=approval_id,
            trace_id=trace_id,
            payload={
                "approval_id": approval_id,
                "order_id": expected_order_id,
                "approved": approved,
                "result_code": result.code,
            },
        )
        await self._session.commit()
        return result
