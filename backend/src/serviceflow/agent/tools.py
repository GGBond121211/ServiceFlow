from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.application.case_service import CaseService
from serviceflow.application.results import CaseResult
from serviceflow.domain.models import Order, RequestedAction


class ServiceTools:
    def __init__(self, session: AsyncSession) -> None:
        self._service = CaseService(session)

    async def get_order(self, order_id: str) -> Order | None:
        return await self._service.get_order(order_id)

    async def cancel_order(self, order_id: str) -> CaseResult:
        return await self._service.cancel_order(order_id)

    async def request_refund(self, order_id: str) -> CaseResult:
        return await self._service.request_refund(order_id)

    async def create_ticket(self, order_id: str, *, kind: str, summary: str) -> CaseResult:
        return await self._service.create_ticket(order_id, kind=kind, summary=summary)

    async def create_approval(self, order_id: str, action: RequestedAction) -> CaseResult:
        return await self._service.create_approval(order_id, action)

    async def decide_approval(self, approval_id: str, *, approved: bool) -> CaseResult:
        return await self._service.decide_approval(approval_id, approved)

    async def get_case_status(self, case_id: str) -> CaseResult | None:
        return await self._service.get_case_status(case_id)
