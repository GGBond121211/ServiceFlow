from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.application.case_service import CaseService
from serviceflow.domain.models import Order, OrderStatus, RequestedAction
from serviceflow.infrastructure.approval_service import ApprovalService
from serviceflow.infrastructure.authorization import Principal
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.tables import RefundRow, TicketRow, UserRow
from serviceflow.infrastructure.tool_executor import ToolExecutionContext, ToolExecutor


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'risk.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [UserRow(id="USER-001", display_name="One"), UserRow(id="USER-002", display_name="Two")]
        )
        for order_id, amount in (("ORDER-LOW", "199.00"), ("ORDER-HIGH", "899.00")):
            await OrderRepository(session).add(
                Order(
                    id=order_id,
                    user_id="USER-001",
                    status=OrderStatus.DELIVERED,
                    total_amount=Decimal(amount),
                    placed_at=datetime(2026, 7, 1, tzinfo=UTC),
                    delivered_at=datetime(2026, 7, 5, tzinfo=UTC),
                )
            )
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool",
    [
        "create_return_request",
        "create_exchange_request",
        "create_support_ticket",
        "create_compensation_request",
    ],
)
async def test_write_tools_require_confirmation_before_writes(database, tool) -> None:
    arguments = {"order_id": "ORDER-LOW"}
    if tool == "create_support_ticket":
        arguments["summary"] = "商品损坏"
    async with database() as session:
        result = await ToolExecutor(session, tenant_id="tenant-a").execute(
            call_id=tool,
            name=tool,
            arguments=arguments,
            context=ToolExecutionContext("USER-001", "tenant-a"),
        )
        ticket_count = await session.scalar(select(func.count()).select_from(TicketRow))

    assert result.code == "confirmation_required"
    assert ticket_count == 0


@pytest.mark.asyncio
async def test_low_value_compensation_can_be_requested_after_confirmation(database) -> None:
    async with database() as session:
        result = await ToolExecutor(session, tenant_id="tenant-a").execute(
            call_id="compensate",
            name="create_compensation_request",
            arguments={"order_id": "ORDER-LOW"},
            context=ToolExecutionContext("USER-001", "tenant-a", confirmed=True),
        )

    assert result.ok is True
    assert result.code == "compensation_requested"
    assert result.data["case_id"]


@pytest.mark.asyncio
async def test_high_refund_requires_approval_and_approval_cannot_be_replayed(database) -> None:
    async with database() as session:
        executor = ToolExecutor(session, tenant_id="tenant-a")
        pending = await executor.execute(
            call_id="refund",
            name="request_refund",
            arguments={"order_id": "ORDER-HIGH"},
            context=ToolExecutionContext("USER-001", "tenant-a", confirmed=True),
        )
        assert pending.code == "approval_required"
        approval = await CaseService(session).create_approval(
            "ORDER-HIGH", RequestedAction.REFUND
        )
        assert approval.case is not None
        approval_id = approval.case.id

        denied = await ApprovalService(session, tenant_id="tenant-a").decide(
            approval_id=approval_id,
            approved=True,
            subject_user_id="USER-001",
            actor=Principal("USER-001", "tenant-a", ("customer",)),
            expected_order_id="ORDER-HIGH",
            expected_action=RequestedAction.REFUND,
        )
        approved = await ApprovalService(session, tenant_id="tenant-a").decide(
            approval_id=approval_id,
            approved=True,
            subject_user_id="USER-001",
            actor=Principal("SUPERVISOR-001", "tenant-a", ("approver",)),
            expected_order_id="ORDER-HIGH",
            expected_action=RequestedAction.REFUND,
        )
        replay = await ApprovalService(session, tenant_id="tenant-a").decide(
            approval_id=approval_id,
            approved=True,
            subject_user_id="USER-001",
            actor=Principal("SUPERVISOR-001", "tenant-a", ("approver",)),
            expected_order_id="ORDER-HIGH",
            expected_action=RequestedAction.REFUND,
        )
        refunds = await session.scalar(select(func.count()).select_from(RefundRow))

    assert denied.code == "unauthorized"
    assert approved.code == "approval_approved"
    assert replay.code == "approval_already_decided"
    assert refunds == 1


@pytest.mark.asyncio
async def test_high_compensation_approval_cannot_turn_into_refund(database) -> None:
    async with database() as session:
        pending = await ToolExecutor(session, tenant_id="tenant-a").execute(
            call_id="compensation",
            name="create_compensation_request",
            arguments={"order_id": "ORDER-HIGH"},
            context=ToolExecutionContext("USER-001", "tenant-a", confirmed=True),
        )
        assert pending.code == "approval_required"
        approval = await CaseService(session).create_approval(
            "ORDER-HIGH", RequestedAction.COMPENSATION
        )
        result = await ApprovalService(session, tenant_id="tenant-a").decide(
            approval_id=approval.case.id,
            approved=True,
            subject_user_id="USER-001",
            actor=Principal("SUPERVISOR-001", "tenant-a", ("approver",)),
            expected_order_id="ORDER-HIGH",
            expected_action=RequestedAction.COMPENSATION,
        )
        refunds = await session.scalar(select(func.count()).select_from(RefundRow))
        tickets = await session.scalar(select(func.count()).select_from(TicketRow))

    assert result.code == "approval_approved"
    assert refunds == 0
    assert tickets == 1
