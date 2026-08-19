from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from serviceflow.application.case_service import CaseService
from serviceflow.domain.models import (
    Approval,
    ApprovalStatus,
    Order,
    OrderStatus,
    Refund,
    RefundStatus,
    RequestedAction,
    Ticket,
    TicketKind,
    TicketStatus,
)
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.tables import UserRow


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    database_path = (tmp_path / "case-service.db").as_posix()
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        database_session.add(UserRow(id="USER-001", display_name="Demo User"))
        database_session.commit()
        yield database_session
    engine.dispose()


def add_order(
    session: Session,
    *,
    order_id: str,
    status: OrderStatus,
    amount: str,
) -> None:
    delivered_at = None
    if status is OrderStatus.DELIVERED:
        delivered_at = datetime(2026, 7, 28, tzinfo=UTC)
    OrderRepository(session).add(
        Order(
            id=order_id,
            user_id="USER-001",
            status=status,
            total_amount=Decimal(amount),
            placed_at=datetime(2026, 7, 1, tzinfo=UTC),
            delivered_at=delivered_at,
        )
    )
    session.commit()


def test_cancel_paid_order_updates_final_state(session: Session) -> None:
    add_order(session, order_id="ORDER-001", status=OrderStatus.PAID, amount="199.00")

    result = CaseService(session).cancel_order("ORDER-001")

    assert result.ok is True
    assert result.code == "order_cancelled"
    assert result.order is not None
    assert result.order.status is OrderStatus.CANCELLED


def test_small_refund_creates_completed_refund(session: Session) -> None:
    add_order(session, order_id="ORDER-002", status=OrderStatus.DELIVERED, amount="199.00")

    result = CaseService(session).request_refund("ORDER-002")

    assert isinstance(result.case, Refund)
    assert result.case.status is RefundStatus.COMPLETED
    assert result.order is not None
    assert result.order.status is OrderStatus.REFUNDED


def test_high_value_refund_creates_pending_approval(session: Session) -> None:
    add_order(session, order_id="ORDER-003", status=OrderStatus.DELIVERED, amount="899.00")

    result = CaseService(session).request_refund("ORDER-003")

    assert isinstance(result.case, Approval)
    assert result.case.status is ApprovalStatus.PENDING
    assert result.order is not None
    assert result.order.status is OrderStatus.DELIVERED


def test_exchange_ticket_updates_order_state(session: Session) -> None:
    add_order(session, order_id="ORDER-004", status=OrderStatus.DELIVERED, amount="499.00")

    result = CaseService(session).create_ticket(
        "ORDER-004",
        kind=TicketKind.EXCHANGE.value,
        summary="Keyboard key does not work",
    )

    assert isinstance(result.case, Ticket)
    assert result.case.kind is TicketKind.EXCHANGE
    assert result.case.status is TicketStatus.OPEN
    assert result.order is not None
    assert result.order.status is OrderStatus.TICKET_OPEN


def test_approved_refund_continues_from_pending_approval(session: Session) -> None:
    add_order(session, order_id="ORDER-005", status=OrderStatus.DELIVERED, amount="899.00")
    pending = CaseService(session).create_approval("ORDER-005", RequestedAction.REFUND)
    assert isinstance(pending.case, Approval)

    result = CaseService(session).decide_approval(pending.case.id, approved=True)

    assert isinstance(result.case, Refund)
    assert result.case.status is RefundStatus.COMPLETED
    assert result.order is not None
    assert result.order.status is OrderStatus.REFUNDED


def test_missing_order_returns_structured_error(session: Session) -> None:
    result = CaseService(session).cancel_order("ORDER-404")

    assert result.ok is False
    assert result.code == "order_not_found"
    assert result.order is None
    assert result.case is None
