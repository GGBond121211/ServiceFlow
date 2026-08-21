from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.domain.models import Order, OrderItem, OrderStatus
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.tables import UserRow


@pytest_asyncio.fixture
async def session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    database_path = (tmp_path / "serviceflow.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as database_session:
        database_session.add(UserRow(id="USER-001", display_name="Demo User"))
        await database_session.commit()
        yield database_session
    await engine.dispose()


def sample_order() -> Order:
    return Order(
        id="ORDER-001",
        user_id="USER-001",
        status=OrderStatus.PAID,
        total_amount=Decimal("199.00"),
        placed_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC),
        items=(
            OrderItem(
                id="ITEM-001",
                order_id="ORDER-001",
                product_name="Mechanical Keyboard",
                category="electronics",
                unit_price=Decimal("199.00"),
                quantity=1,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_add_then_get_restores_order(session: AsyncSession) -> None:
    repository = OrderRepository(session)
    order = sample_order()

    await repository.add(order)
    await session.commit()
    session.expire_all()

    assert await repository.get(order.id) == order


@pytest.mark.asyncio
async def test_set_status_persists_change(session: AsyncSession) -> None:
    repository = OrderRepository(session)
    await repository.add(sample_order())
    await session.commit()

    updated = await repository.set_status("ORDER-001", OrderStatus.CANCELLED)
    await session.commit()
    session.expire_all()

    assert updated.status is OrderStatus.CANCELLED
    assert await repository.get("ORDER-001") == updated


@pytest.mark.asyncio
async def test_get_missing_order_returns_none(session: AsyncSession) -> None:
    assert await OrderRepository(session).get("ORDER-404") is None
