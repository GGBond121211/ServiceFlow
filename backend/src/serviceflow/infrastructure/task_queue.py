from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.infrastructure.database import ensure_utc
from serviceflow.infrastructure.event_log import EventLog
from serviceflow.infrastructure.tables import TaskEnvelopeRow
from serviceflow.infrastructure.trace_context import (
    trace_id_from_traceparent,
    validate_traceparent,
)


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    MANUAL_REQUIRED = "manual_required"


@dataclass(frozen=True, slots=True)
class TaskEnvelope:
    id: str
    run_id: str
    session_id: str
    case_id: str
    operation_id: str
    idempotency_key: str
    task_type: str
    payload: dict[str, object]
    attempt: int
    max_attempts: int
    deadline: datetime
    status: TaskStatus
    error_class: str
    available_at: datetime
    traceparent: str
    created_at: datetime
    updated_at: datetime
    tracestate: str | None = None
    lease_until: datetime | None = None

    def __post_init__(self) -> None:
        validate_traceparent(self.traceparent)


class TaskQueue:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(self, envelope: TaskEnvelope) -> TaskEnvelope:
        existing = await self.get(envelope.id)
        if existing is not None:
            return existing
        self._session.add(
            TaskEnvelopeRow(
                id=envelope.id,
                run_id=envelope.run_id,
                session_id=envelope.session_id,
                case_id=envelope.case_id,
                operation_id=envelope.operation_id,
                idempotency_key=envelope.idempotency_key,
                task_type=envelope.task_type,
                payload=envelope.payload,
                attempt=envelope.attempt,
                max_attempts=envelope.max_attempts,
                deadline=envelope.deadline,
                status=envelope.status.value,
                error_class=envelope.error_class,
                available_at=envelope.available_at,
                lease_until=envelope.lease_until,
                traceparent=envelope.traceparent,
                tracestate=envelope.tracestate,
                created_at=envelope.created_at,
                updated_at=envelope.updated_at,
            )
        )
        await self._session.flush()
        return envelope

    async def get(self, task_id: str) -> TaskEnvelope | None:
        row = await self._session.get(TaskEnvelopeRow, task_id)
        return None if row is None else _to_envelope(row)

    async def recover_expired(self, *, now: datetime) -> int:
        rows = tuple(
            await self._session.scalars(
                select(TaskEnvelopeRow).where(
                    TaskEnvelopeRow.status == TaskStatus.RUNNING.value,
                    TaskEnvelopeRow.lease_until < now,
                )
            )
        )
        for row in rows:
            row.status = TaskStatus.QUEUED.value
            row.lease_until = None
            row.updated_at = now
            await self._append_event(row, "task_lease_recovered", now)
        await self._session.flush()
        return len(rows)

    async def expire_deadlines(self, *, now: datetime) -> int:
        rows = tuple(
            await self._session.scalars(
                select(TaskEnvelopeRow).where(
                    TaskEnvelopeRow.status.in_(
                        (TaskStatus.QUEUED.value, TaskStatus.RUNNING.value)
                    ),
                    TaskEnvelopeRow.deadline <= now,
                )
            )
        )
        for row in rows:
            row.status = TaskStatus.DEAD_LETTER.value
            row.error_class = "deadline_exceeded"
            row.lease_until = None
            row.updated_at = now
            await self._append_event(row, "task_deadline_exceeded", now)
        await self._session.flush()
        return len(rows)

    async def claim(self, *, now: datetime, visibility_timeout_s: int) -> TaskEnvelope | None:
        row = await self._session.scalar(
            select(TaskEnvelopeRow)
            .where(
                or_(
                    TaskEnvelopeRow.status == TaskStatus.QUEUED.value,
                    (
                        (TaskEnvelopeRow.status == TaskStatus.RUNNING.value)
                        & (TaskEnvelopeRow.lease_until < now)
                    ),
                ),
                TaskEnvelopeRow.available_at <= now,
                TaskEnvelopeRow.deadline > now,
            )
            .order_by(TaskEnvelopeRow.created_at, TaskEnvelopeRow.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return None
        row.status = TaskStatus.RUNNING.value
        row.attempt += 1
        row.lease_until = now + timedelta(seconds=visibility_timeout_s)
        row.updated_at = now
        await self._append_event(row, "task_claimed", now)
        await self._session.flush()
        return _to_envelope(row)

    async def complete(self, task_id: str, *, now: datetime) -> TaskEnvelope:
        row = await self._required(task_id)
        row.status = TaskStatus.SUCCEEDED.value
        row.lease_until = None
        row.updated_at = now
        await self._append_event(row, "task_succeeded", now)
        await self._session.flush()
        return _to_envelope(row)

    async def fail(
        self,
        task_id: str,
        *,
        now: datetime,
        error_class: str,
        retryable: bool,
        retry_delay_s: int = 1,
    ) -> TaskEnvelope:
        row = await self._required(task_id)
        row.error_class = error_class
        row.lease_until = None
        row.updated_at = now
        if retryable and row.attempt < row.max_attempts and now < ensure_utc(row.deadline):
            row.status = TaskStatus.QUEUED.value
            row.available_at = now + timedelta(seconds=retry_delay_s)
            event_type = "task_retry_scheduled"
        else:
            row.status = (
                TaskStatus.DEAD_LETTER.value if retryable else TaskStatus.MANUAL_REQUIRED.value
            )
            event_type = (
                "task_dead_lettered" if retryable else "task_manual_required"
            )
        await self._append_event(
            row,
            event_type,
            now,
            payload={"error_class": error_class, "retryable": retryable},
        )
        await self._session.flush()
        return _to_envelope(row)

    async def _append_event(
        self,
        row: TaskEnvelopeRow,
        event_type: str,
        now: datetime,
        *,
        payload: dict[str, object] | None = None,
    ) -> None:
        await EventLog(self._session).append(
            event_type=event_type,
            tenant_id="system",
            actor="worker",
            session_id=row.session_id,
            case_id=row.case_id,
            operation_id=row.operation_id,
            run_id=row.run_id,
            trace_id=trace_id_from_traceparent(row.traceparent),
            payload={"task_id": row.id, "task_type": row.task_type, **(payload or {})},
            at=now,
        )

    async def _required(self, task_id: str) -> TaskEnvelopeRow:
        row = await self._session.get(TaskEnvelopeRow, task_id)
        if row is None:
            raise LookupError("task_not_found")
        return row


def _to_envelope(row: TaskEnvelopeRow) -> TaskEnvelope:
    return TaskEnvelope(
        id=row.id,
        run_id=row.run_id,
        session_id=row.session_id,
        case_id=row.case_id,
        operation_id=row.operation_id,
        idempotency_key=row.idempotency_key,
        task_type=row.task_type,
        payload=dict(row.payload),
        attempt=row.attempt,
        max_attempts=row.max_attempts,
        deadline=ensure_utc(row.deadline),
        status=TaskStatus(row.status),
        error_class=row.error_class,
        available_at=ensure_utc(row.available_at),
        lease_until=ensure_utc(row.lease_until),
        traceparent=row.traceparent,
        tracestate=row.tracestate,
        created_at=ensure_utc(row.created_at),
        updated_at=ensure_utc(row.updated_at),
    )
