from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.event_log import EventLog
from serviceflow.infrastructure.task_queue import TaskEnvelope, TaskQueue, TaskStatus

TRACEPARENT = "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'worker.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_worker_restart_recovers_expired_lease(database) -> None:
    created = datetime(2026, 9, 4, 8, 0, tzinfo=UTC)
    envelope = TaskEnvelope(
        id="TASK-001",
        run_id="RUN-001",
        session_id="SESSION-001",
        case_id="CASE-001",
        operation_id="OP-001",
        idempotency_key="ACTION-001",
        task_type="provider_reconcile",
        payload={"provider_reference": "provider-ref"},
        attempt=0,
        max_attempts=3,
        deadline=created + timedelta(hours=1),
        status=TaskStatus.QUEUED,
        error_class="none",
        available_at=created,
        traceparent=TRACEPARENT,
        created_at=created,
        updated_at=created,
    )
    async with database() as first_worker:
        queue = TaskQueue(first_worker)
        await queue.enqueue(envelope)
        claimed = await queue.claim(now=created, visibility_timeout_s=10)
        await first_worker.commit()
    assert claimed is not None and claimed.status is TaskStatus.RUNNING

    restarted_at = created + timedelta(seconds=11)
    async with database() as second_worker:
        queue = TaskQueue(second_worker)
        assert await queue.recover_expired(now=restarted_at) == 1
        reclaimed = await queue.claim(now=restarted_at, visibility_timeout_s=10)
        assert reclaimed is not None
        completed = await queue.complete(reclaimed.id, now=restarted_at)
        await second_worker.commit()

    assert completed.status is TaskStatus.SUCCEEDED
    assert completed.attempt == 2
    assert completed.traceparent == TRACEPARENT


def test_task_rejects_missing_trace_context() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="traceparent"):
        TaskEnvelope(
            id="TASK-BAD",
            run_id="RUN",
            session_id="SESSION",
            case_id="CASE",
            operation_id="OP",
            idempotency_key="KEY",
            task_type="provider_reconcile",
            payload={},
            attempt=0,
            max_attempts=1,
            deadline=now + timedelta(minutes=1),
            status=TaskStatus.QUEUED,
            error_class="none",
            available_at=now,
            traceparent="",
            created_at=now,
            updated_at=now,
        )


@pytest.mark.asyncio
async def test_retryable_task_reaches_dead_letter_after_max_attempts(database) -> None:
    now = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)
    envelope = TaskEnvelope(
        id="TASK-DLQ",
        run_id="RUN",
        session_id="SESSION",
        case_id="CASE",
        operation_id="OP",
        idempotency_key="KEY",
        task_type="provider_reconcile",
        payload={},
        attempt=0,
        max_attempts=2,
        deadline=now + timedelta(minutes=5),
        status=TaskStatus.QUEUED,
        error_class="none",
        available_at=now,
        traceparent=TRACEPARENT,
        created_at=now,
        updated_at=now,
    )
    async with database() as session:
        queue = TaskQueue(session)
        await queue.enqueue(envelope)
        first = await queue.claim(now=now, visibility_timeout_s=10)
        assert first is not None
        await queue.fail(
            first.id,
            now=now,
            error_class="server_error",
            retryable=True,
            retry_delay_s=0,
        )
        second = await queue.claim(now=now, visibility_timeout_s=10)
        assert second is not None
        final = await queue.fail(
            second.id,
            now=now,
            error_class="server_error",
            retryable=True,
            retry_delay_s=0,
        )
        await session.commit()

    assert final.status is TaskStatus.DEAD_LETTER
    assert final.attempt == 2


@pytest.mark.asyncio
async def test_expired_task_is_dead_lettered_and_audited(database) -> None:
    now = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
    envelope = TaskEnvelope(
        id="TASK-EXPIRED",
        run_id="RUN-EXPIRED",
        session_id="SESSION-EXPIRED",
        case_id="CASE-EXPIRED",
        operation_id="OP-EXPIRED",
        idempotency_key="KEY-EXPIRED",
        task_type="provider_reconcile",
        payload={},
        attempt=0,
        max_attempts=3,
        deadline=now,
        status=TaskStatus.QUEUED,
        error_class="none",
        available_at=now - timedelta(minutes=1),
        traceparent=TRACEPARENT,
        created_at=now - timedelta(minutes=1),
        updated_at=now - timedelta(minutes=1),
    )
    async with database() as session:
        queue = TaskQueue(session)
        await queue.enqueue(envelope)
        assert await queue.expire_deadlines(now=now) == 1
        expired = await queue.get(envelope.id)
        events = await EventLog(session).read_operation(envelope.operation_id)
        await session.commit()

    assert expired is not None
    assert expired.status is TaskStatus.DEAD_LETTER
    assert expired.error_class == "deadline_exceeded"
    assert [event.event_type for event in events] == ["task_deadline_exceeded"]


@pytest.mark.asyncio
async def test_nonretryable_task_goes_to_manual_queue_with_audit(database) -> None:
    now = datetime(2026, 9, 4, 11, 0, tzinfo=UTC)
    envelope = TaskEnvelope(
        id="TASK-MANUAL",
        run_id="RUN-MANUAL",
        session_id="SESSION-MANUAL",
        case_id="CASE-MANUAL",
        operation_id="OP-MANUAL",
        idempotency_key="KEY-MANUAL",
        task_type="provider_reconcile",
        payload={},
        attempt=0,
        max_attempts=3,
        deadline=now + timedelta(minutes=5),
        status=TaskStatus.QUEUED,
        error_class="none",
        available_at=now,
        traceparent=TRACEPARENT,
        created_at=now,
        updated_at=now,
    )
    async with database() as session:
        queue = TaskQueue(session)
        await queue.enqueue(envelope)
        claimed = await queue.claim(now=now, visibility_timeout_s=10)
        assert claimed is not None
        manual = await queue.fail(
            claimed.id,
            now=now,
            error_class="permission",
            retryable=False,
        )
        events = await EventLog(session).read_operation(envelope.operation_id)
        await session.commit()

    assert manual.status is TaskStatus.MANUAL_REQUIRED
    assert [event.event_type for event in events] == [
        "task_claimed",
        "task_manual_required",
    ]
