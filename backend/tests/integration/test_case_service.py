from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


@pytest_asyncio.fixture
async def session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    database_path = (tmp_path / "case-service.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async_session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with async_session_factory() as database_session:
        database_session.add(UserRow(id="USER-001", display_name="Demo User"))
        await database_session.commit()
        yield database_session
    await engine.dispose()


async def add_order(
    session: AsyncSession,
    *,
    order_id: str,
    status: OrderStatus,
    amount: str,
) -> None:
    delivered_at = None
    if status is OrderStatus.DELIVERED:
        delivered_at = datetime(2026, 7, 28, tzinfo=UTC)
    await OrderRepository(session).add(
        Order(
            id=order_id,
            user_id="USER-001",
            status=status,
            total_amount=Decimal(amount),
            placed_at=datetime(2026, 7, 1, tzinfo=UTC),
            delivered_at=delivered_at,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_cancel_paid_order_updates_final_state(session: AsyncSession) -> None:
    await add_order(session, order_id="ORDER-001", status=OrderStatus.PAID, amount="199.00")

    result = await CaseService(session).cancel_order("ORDER-001")

    assert result.ok is True
    assert result.code == "order_cancelled"
    assert result.order is not None
    assert result.order.status is OrderStatus.CANCELLED


@pytest.mark.asyncio
async def test_small_refund_creates_completed_refund(session: AsyncSession) -> None:
    await add_order(session, order_id="ORDER-002", status=OrderStatus.DELIVERED, amount="199.00")

    result = await CaseService(session).request_refund("ORDER-002")

    assert isinstance(result.case, Refund)
    assert result.case.status is RefundStatus.COMPLETED
    assert result.order is not None
    assert result.order.status is OrderStatus.REFUNDED


@pytest.mark.asyncio
async def test_high_value_refund_creates_pending_approval(session: AsyncSession) -> None:
    await add_order(session, order_id="ORDER-003", status=OrderStatus.DELIVERED, amount="899.00")

    result = await CaseService(session).request_refund("ORDER-003")

    assert isinstance(result.case, Approval)
    assert result.case.status is ApprovalStatus.PENDING
    assert result.order is not None
    assert result.order.status is OrderStatus.DELIVERED


@pytest.mark.asyncio
async def test_exchange_ticket_updates_order_state(session: AsyncSession) -> None:
    await add_order(session, order_id="ORDER-004", status=OrderStatus.DELIVERED, amount="499.00")

    result = await CaseService(session).create_ticket(
        "ORDER-004",
        kind=TicketKind.EXCHANGE.value,
        summary="Keyboard key does not work",
    )

    assert isinstance(result.case, Ticket)
    assert result.case.kind is TicketKind.EXCHANGE
    assert result.case.status is TicketStatus.OPEN
    assert result.order is not None
    assert result.order.status is OrderStatus.TICKET_OPEN


@pytest.mark.asyncio
async def test_approved_refund_continues_from_pending_approval(session: AsyncSession) -> None:
    await add_order(session, order_id="ORDER-005", status=OrderStatus.DELIVERED, amount="899.00")
    pending = await CaseService(session).create_approval("ORDER-005", RequestedAction.REFUND)
    assert isinstance(pending.case, Approval)

    result = await CaseService(session).decide_approval(pending.case.id, approved=True)

    assert isinstance(result.case, Refund)
    assert result.case.status is RefundStatus.COMPLETED
    assert result.order is not None
    assert result.order.status is OrderStatus.REFUNDED


@pytest.mark.asyncio
async def test_missing_order_returns_structured_error(session: AsyncSession) -> None:
    result = await CaseService(session).cancel_order("ORDER-404")

    assert result.ok is False
    assert result.code == "order_not_found"
    assert result.order is None
    assert result.case is None
