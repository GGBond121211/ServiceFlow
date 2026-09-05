from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.application.session_service import SessionService
from serviceflow.domain.cases import CaseType
from serviceflow.domain.models import Order, OrderStatus
from serviceflow.domain.operations import ActionType, OperationStatus
from serviceflow.domain.sessions import Channel
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.event_log import EventLog
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.support_queue import SupportQueue
from serviceflow.infrastructure.tables import UserRow
from serviceflow.infrastructure.tool_executor import ToolExecutionContext, ToolExecutor


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'scope.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [UserRow(id="USER-001", display_name="One"), UserRow(id="USER-002", display_name="Two")]
        )
        await OrderRepository(session).add(
            Order(
                id="ORDER-001",
                user_id="USER-001",
                status=OrderStatus.DELIVERED,
                total_amount=Decimal("199.00"),
                placed_at=datetime(2026, 7, 1, tzinfo=UTC),
                delivered_at=datetime(2026, 7, 5, tzinfo=UTC),
            )
        )
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_executor_rejects_cross_tenant_and_cross_user(database) -> None:
    async with database() as session:
        executor = ToolExecutor(session, tenant_id="tenant-a")
        wrong_tenant = await executor.execute(
            call_id="tenant",
            name="get_order",
            arguments={"order_id": "ORDER-001"},
            context=ToolExecutionContext("USER-001", "tenant-b"),
        )
        wrong_user = await executor.execute(
            call_id="user",
            name="get_order",
            arguments={"order_id": "ORDER-001"},
            context=ToolExecutionContext("USER-002", "tenant-a"),
        )

    assert wrong_tenant.code == "unauthorized"
    assert wrong_user.code == "unauthorized"
    assert wrong_tenant.data == wrong_user.data == {}


@pytest.mark.asyncio
async def test_handoff_is_persisted_redacted_and_auditable(database) -> None:
    async with database() as session:
        result = await ToolExecutor(session, tenant_id="tenant-a").execute(
            call_id="handoff",
            name="request_handoff",
            arguments={"reason": "政策冲突，请联系 alex@example.com 或 13800138000"},
            context=ToolExecutionContext(
                "USER-001",
                "tenant-a",
                confirmed=True,
                session_id="SESSION-001",
                trace_id="trace-001",
            ),
        )
        record = await SupportQueue(session).get(str(result.data["handoff_id"]))
        events = await EventLog(session).read_session("SESSION-001")

    assert result.code == "handoff_created"
    assert record is not None
    assert "alex@example.com" not in record.reason
    assert "13800138000" not in record.reason
    assert record.trace_id == "trace-001"
    assert [event.event_type for event in events] == ["handoff_created"]
    assert events[0].payload["reason_code"] == "user_requested"


@pytest.mark.asyncio
async def test_missing_policy_retriever_creates_handoff(database) -> None:
    async with database() as session:
        result = await ToolExecutor(session, tenant_id="tenant-a").execute(
            call_id="policy",
            name="search_policy_evidence",
            arguments={"query": "这个商品能不能退"},
            context=ToolExecutionContext("USER-001", "tenant-a", session_id="SESSION-002"),
        )

    assert result.code == "handoff_created"
    assert result.data["reason_code"] == "policy_evidence_unavailable"


@pytest.mark.asyncio
async def test_unknown_provider_operation_creates_reconciliation_handoff(database) -> None:
    service = SessionService(database)
    conversation = await service.start_session(
        tenant_id="tenant-a", user_id="USER-001", channel=Channel.WEB
    )
    goal = await service.open_goal(
        session_id=conversation.id,
        order_id="ORDER-001",
        scene_code="refund",
        created_by="model",
    )
    case = await service.open_case(
        goal_id=goal.id,
        order_id="ORDER-001",
        case_type=CaseType.REFUND,
        reason="退款结果未知",
    )
    begin = await service.begin_operation(
        case_id=case.id,
        action_type=ActionType.REFUND,
        action_id="ACTION-UNKNOWN-001",
        payload={"order_id": "ORDER-001"},
    )
    await service.finish_operation(
        operation_id=begin.operation.id,
        status=OperationStatus.UNKNOWN,
        result_code="provider_timeout",
    )

    async with database() as session:
        result = await ToolExecutor(session, tenant_id="tenant-a").execute(
            call_id="poll",
            name="poll_provider_operation",
            arguments={"operation_id": begin.operation.id},
            context=ToolExecutionContext(
                "USER-001", "tenant-a", session_id=conversation.id, case_id=case.id
            ),
        )

    assert result.code == "handoff_created"
    assert result.data["operation_status"] == "unknown"
