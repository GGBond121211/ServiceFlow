from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.application.session_service import SessionService
from serviceflow.domain.cases import CaseType
from serviceflow.domain.operations import ActionType, OperationStatus
from serviceflow.domain.sessions import Channel
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.outbox import Outbox
from serviceflow.infrastructure.provider_adapters import ProviderStatus
from serviceflow.infrastructure.provider_event_inbox import (
    ProviderEvent,
    ProviderEventInbox,
    ProviderEventProcessor,
)
from serviceflow.infrastructure.tables import OutboxMessageRow

TRACEPARENT = "00-33333333333333333333333333333333-4444444444444444-01"


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'messages.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_webhook_and_outbox_delivery_are_idempotent(database) -> None:
    event = ProviderEvent(
        provider="fake-refund",
        event_id="EVENT-001",
        event_type="refund.succeeded",
        operation_id="OP-001",
        payload={"status": "succeeded"},
        traceparent=TRACEPARENT,
    )
    delivered: list[str] = []

    async with database() as session:
        inbox = ProviderEventInbox(session)
        assert await inbox.record(event) is True
        assert await inbox.record(event) is False
        outbox = Outbox(session)
        first = await outbox.enqueue(
            dedupe_key="notify:OP-001:succeeded",
            aggregate_type="operation",
            aggregate_id="OP-001",
            event_type="operation_completed",
            payload={"operation_id": "OP-001"},
            traceparent=TRACEPARENT,
        )
        duplicate = await outbox.enqueue(
            dedupe_key="notify:OP-001:succeeded",
            aggregate_type="operation",
            aggregate_id="OP-001",
            event_type="operation_completed",
            payload={"operation_id": "OP-001"},
            traceparent=TRACEPARENT,
        )

        async def sender(message) -> None:
            delivered.append(message.id)

        await outbox.deliver(first.id, sender)
        final = await outbox.deliver(first.id, sender)
        await session.commit()

    assert duplicate.id == first.id
    assert delivered == [first.id]
    assert final.status == "sent"
    assert final.attempt == 1


@pytest.mark.asyncio
async def test_duplicate_webhook_advances_operation_and_outbox_once(database) -> None:
    service = SessionService(database)
    conversation = await service.start_session(
        tenant_id="tenant-a", user_id="USER-001", channel=Channel.EVAL
    )
    goal = await service.open_goal(
        session_id=conversation.id,
        order_id="ORDER-001",
        scene_code="refund",
        created_by="test",
    )
    case = await service.open_case(
        goal_id=goal.id,
        order_id="ORDER-001",
        case_type=CaseType.REFUND,
        reason="Webhook 去重测试",
    )
    begin = await service.begin_operation(
        case_id=case.id,
        action_type=ActionType.REFUND,
        action_id="ACTION-WEBHOOK",
        payload={"order_id": "ORDER-001"},
    )
    await service.finish_operation(
        operation_id=begin.operation.id,
        status=OperationStatus.PENDING,
        provider_ref="provider-ref",
    )
    event = ProviderEvent(
        provider="fake-refund",
        event_id="EVENT-APPLY-001",
        event_type="refund.succeeded",
        operation_id=begin.operation.id,
        payload={"status": "succeeded"},
        traceparent=TRACEPARENT,
    )
    processor = ProviderEventProcessor(database)

    assert await processor.apply(event, ProviderStatus.SUCCEEDED) is True
    assert await processor.apply(event, ProviderStatus.SUCCEEDED) is False
    state = await service.final_state(case.id)
    async with database() as session:
        outbox_count = await session.scalar(select(func.count()).select_from(OutboxMessageRow))

    assert state["operations"][0]["status"] == "succeeded"
    assert outbox_count == 1
