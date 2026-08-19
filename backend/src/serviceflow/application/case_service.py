from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from serviceflow.application.results import CaseResult
from serviceflow.domain.models import (
    ApprovalStatus,
    Order,
    OrderStatus,
    RefundStatus,
    RequestedAction,
    TicketKind,
)
from serviceflow.domain.policies import APPROVAL_AMOUNT_THRESHOLD
from serviceflow.infrastructure.case_repository import CaseRepository
from serviceflow.infrastructure.repositories import OrderRepository


class CaseService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._orders = OrderRepository(session)
        self._cases = CaseRepository(session)

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def cancel_order(self, order_id: str) -> CaseResult:
        order = self._orders.get(order_id)
        if order is None:
            return _order_not_found()
        if order.status is not OrderStatus.PAID:
            return CaseResult(ok=False, code="action_not_supported", order=order)
        updated = self._orders.set_status(order_id, OrderStatus.CANCELLED)
        self._session.commit()
        return CaseResult(ok=True, code="order_cancelled", order=updated)

    def request_refund(self, order_id: str) -> CaseResult:
        order = self._orders.get(order_id)
        if order is None:
            return _order_not_found()
        if order.status is not OrderStatus.DELIVERED:
            return CaseResult(ok=False, code="action_not_supported", order=order)
        if order.total_amount > APPROVAL_AMOUNT_THRESHOLD:
            return self.create_approval(order_id, RequestedAction.REFUND)

        refund = self._cases.create_refund(
            case_id=_new_case_id("REFUND"),
            order_id=order.id,
            amount=order.total_amount,
            status=RefundStatus.COMPLETED,
            created_at=datetime.now(UTC),
        )
        updated = self._orders.set_status(order.id, OrderStatus.REFUNDED)
        self._session.commit()
        return CaseResult(ok=True, code="refund_completed", order=updated, case=refund)

    def create_ticket(self, order_id: str, kind: str, summary: str) -> CaseResult:
        order = self._orders.get(order_id)
        if order is None:
            return _order_not_found()
        try:
            ticket_kind = TicketKind(kind)
        except ValueError:
            return CaseResult(ok=False, code="action_not_supported", order=order)
        ticket = self._cases.create_ticket(
            case_id=_new_case_id("TICKET"),
            order_id=order.id,
            kind=ticket_kind,
            summary=summary,
            created_at=datetime.now(UTC),
        )
        updated = self._orders.set_status(order.id, OrderStatus.TICKET_OPEN)
        self._session.commit()
        return CaseResult(ok=True, code="ticket_created", order=updated, case=ticket)

    def create_approval(self, order_id: str, action: RequestedAction) -> CaseResult:
        order = self._orders.get(order_id)
        if order is None:
            return _order_not_found()
        approval = self._cases.create_approval(
            case_id=_new_case_id("APPROVAL"),
            order_id=order.id,
            requested_action=action,
            created_at=datetime.now(UTC),
        )
        self._session.commit()
        return CaseResult(ok=True, code="approval_pending", order=order, case=approval)

    def decide_approval(self, approval_id: str, approved: bool) -> CaseResult:
        approval = self._cases.get_approval(approval_id)
        if approval is None:
            return CaseResult(ok=False, code="case_not_found")
        order = self._orders.get(approval.order_id)
        if order is None:
            return _order_not_found()
        status = ApprovalStatus.REJECTED
        if approved:
            status = ApprovalStatus.APPROVED
        updated_approval = self._cases.set_approval_status(approval.id, status)

        if approved and approval.requested_action is RequestedAction.REFUND:
            refund = self._cases.create_refund(
                case_id=_new_case_id("REFUND"),
                order_id=order.id,
                amount=order.total_amount,
                status=RefundStatus.COMPLETED,
                created_at=datetime.now(UTC),
            )
            updated_order = self._orders.set_status(order.id, OrderStatus.REFUNDED)
            self._session.commit()
            return CaseResult(
                ok=True,
                code="approval_approved",
                order=updated_order,
                case=refund,
            )

        self._session.commit()
        code = "approval_rejected"
        if approved:
            code = "approval_approved"
        return CaseResult(ok=True, code=code, order=order, case=updated_approval)

    def get_case_status(self, case_id: str) -> CaseResult | None:
        case = self._cases.get(case_id)
        if case is None:
            return None
        return CaseResult(
            ok=True,
            code="case_found",
            order=self._orders.get(case.order_id),
            case=case,
        )


def _new_case_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def _order_not_found() -> CaseResult:
    return CaseResult(ok=False, code="order_not_found")
