from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.domain.models import Order, OrderStatus
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.tables import UserRow
from serviceflow.infrastructure.tool_executor import ToolExecutionContext, ToolExecutor


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'tool.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                UserRow(id="USER-001", display_name="User 1"),
                UserRow(id="USER-002", display_name="User 2"),
            ]
        )
        await OrderRepository(session).add(
            Order(
                id="ORDER-001",
                user_id="USER-001",
                status=OrderStatus.DELIVERED,
                total_amount=Decimal("800.00"),
                placed_at=datetime(2026, 7, 1, tzinfo=UTC),
                delivered_at=datetime(2026, 7, 30, tzinfo=UTC),
            )
        )
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_executor_rejects_cross_user_order(database) -> None:
    async with database() as session:
        result = await ToolExecutor(session, tenant_id="tenant-a").execute(
            call_id="call-1",
            name="get_order",
            arguments={"order_id": "ORDER-001"},
            context=ToolExecutionContext("USER-002", "tenant-a"),
        )

    assert result.code == "unauthorized"


@pytest.mark.asyncio
async def test_executor_requires_confirmation_before_refund(database) -> None:
    async with database() as session:
        result = await ToolExecutor(session, tenant_id="tenant-a").execute(
            call_id="call-1",
            name="request_refund",
            arguments={"order_id": "ORDER-001"},
            context=ToolExecutionContext("USER-001", "tenant-a"),
        )

    assert result.code == "confirmation_required"


@pytest.mark.asyncio
async def test_executor_requires_approval_after_confirmation(database) -> None:
    async with database() as session:
        result = await ToolExecutor(session, tenant_id="tenant-a").execute(
            call_id="call-1",
            name="request_refund",
            arguments={"order_id": "ORDER-001"},
            context=ToolExecutionContext("USER-001", "tenant-a", confirmed=True),
        )

    assert result.code == "approval_required"
