from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from serviceflow.domain.models import (
    Approval,
    ApprovalStatus,
    Refund,
    RefundStatus,
    RequestedAction,
    Ticket,
    TicketKind,
    TicketStatus,
)
from serviceflow.infrastructure.tables import ApprovalRow, RefundRow, TicketRow

CaseEntity = Refund | Ticket | Approval


class CaseRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_refund(
        self,
        *,
        case_id: str,
        order_id: str,
        amount: Decimal,
        status: RefundStatus,
        created_at: datetime,
    ) -> Refund:
        row = RefundRow(
            id=case_id,
            order_id=order_id,
            amount=amount,
            status=status.value,
            created_at=created_at,
        )
        self._session.add(row)
        self._session.flush()
        return _refund_to_domain(row)

    def create_ticket(
        self,
        *,
        case_id: str,
        order_id: str,
        kind: TicketKind,
        summary: str,
        created_at: datetime,
    ) -> Ticket:
        row = TicketRow(
            id=case_id,
            order_id=order_id,
            kind=kind.value,
            status=TicketStatus.OPEN.value,
            summary=summary,
            created_at=created_at,
        )
        self._session.add(row)
        self._session.flush()
        return _ticket_to_domain(row)

    def create_approval(
        self,
        *,
        case_id: str,
        order_id: str,
        requested_action: RequestedAction,
        created_at: datetime,
    ) -> Approval:
        row = ApprovalRow(
            id=case_id,
            order_id=order_id,
            requested_action=requested_action.value,
            status=ApprovalStatus.PENDING.value,
            created_at=created_at,
        )
        self._session.add(row)
        self._session.flush()
        return _approval_to_domain(row)

    def get(self, case_id: str) -> CaseEntity | None:
        refund = self._session.get(RefundRow, case_id)
        if refund is not None:
            return _refund_to_domain(refund)
        ticket = self._session.get(TicketRow, case_id)
        if ticket is not None:
            return _ticket_to_domain(ticket)
        approval = self._session.get(ApprovalRow, case_id)
        if approval is not None:
            return _approval_to_domain(approval)
        return None

    def get_approval(self, approval_id: str) -> Approval | None:
        row = self._session.get(ApprovalRow, approval_id)
        if row is None:
            return None
        return _approval_to_domain(row)

    def set_approval_status(
        self,
        approval_id: str,
        status: ApprovalStatus,
    ) -> Approval:
        row = self._session.get(ApprovalRow, approval_id)
        if row is None:
            raise LookupError("case_not_found")
        row.status = status.value
        self._session.flush()
        return _approval_to_domain(row)


def _refund_to_domain(row: RefundRow) -> Refund:
    return Refund(
        id=row.id,
        order_id=row.order_id,
        amount=row.amount,
        status=RefundStatus(row.status),
        created_at=_with_utc(row.created_at),
    )


def _ticket_to_domain(row: TicketRow) -> Ticket:
    return Ticket(
        id=row.id,
        order_id=row.order_id,
        kind=TicketKind(row.kind),
        status=TicketStatus(row.status),
        summary=row.summary,
        created_at=_with_utc(row.created_at),
    )


def _approval_to_domain(row: ApprovalRow) -> Approval:
    return Approval(
        id=row.id,
        order_id=row.order_id,
        requested_action=RequestedAction(row.requested_action),
        status=ApprovalStatus(row.status),
        created_at=_with_utc(row.created_at),
    )


def _with_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)
