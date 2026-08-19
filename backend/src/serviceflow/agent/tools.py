from sqlalchemy.orm import Session

from serviceflow.application.case_service import CaseService
from serviceflow.application.results import CaseResult
from serviceflow.domain.models import Order, RequestedAction


class ServiceTools:
    def __init__(self, session: Session) -> None:
        self._service = CaseService(session)

    def get_order(self, order_id: str) -> Order | None:
        return self._service.get_order(order_id)

    def cancel_order(self, order_id: str) -> CaseResult:
        return self._service.cancel_order(order_id)

    def request_refund(self, order_id: str) -> CaseResult:
        return self._service.request_refund(order_id)

    def create_ticket(self, order_id: str, *, kind: str, summary: str) -> CaseResult:
        return self._service.create_ticket(order_id, kind=kind, summary=summary)

    def create_approval(self, order_id: str, action: RequestedAction) -> CaseResult:
        return self._service.create_approval(order_id, action)

    def decide_approval(self, approval_id: str, *, approved: bool) -> CaseResult:
        return self._service.decide_approval(approval_id, approved)

    def get_case_status(self, case_id: str) -> CaseResult | None:
        return self._service.get_case_status(case_id)
