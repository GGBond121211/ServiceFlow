import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from serviceflow.domain.models import Order, OrderItem, OrderStatus
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.seed import seed_database
from serviceflow.infrastructure.tables import OrderRow

DATABASE_URL = os.getenv("SERVICEFLOW_DATABASE_URL", "")


@pytest_asyncio.fixture
async def mysql_session() -> AsyncIterator[AsyncSession]:
    if not DATABASE_URL.startswith("mysql+aiomysql://"):
        pytest.skip("SERVICEFLOW_DATABASE_URL 未配置为 mysql+aiomysql")

    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        await seed_database(session)
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_mysql_async_repository_and_seed(mysql_session: AsyncSession) -> None:
    repository = OrderRepository(mysql_session)
    existing = await repository.get("ORDER-001")
    assert existing is not None

    new_order = Order(
        id="ORDER-ASYNC-MYSQL",
        user_id="USER-001",
        status=OrderStatus.PAID,
        total_amount=Decimal("19.90"),
        placed_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        items=(
            OrderItem(
                id="ITEM-ASYNC-MYSQL",
                order_id="ORDER-ASYNC-MYSQL",
                product_name="Async smoke test",
                category="test",
                unit_price=Decimal("19.90"),
                quantity=1,
            ),
        ),
    )
    await repository.add(new_order)
    await mysql_session.commit()

    row = await mysql_session.scalar(
        select(OrderRow).where(OrderRow.id == "ORDER-ASYNC-MYSQL")
    )
    assert row is not None
    assert row.status == OrderStatus.PAID.value
