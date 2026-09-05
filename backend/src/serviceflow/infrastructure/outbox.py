from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.infrastructure.database import ensure_utc
from serviceflow.infrastructure.tables import OutboxMessageRow
from serviceflow.infrastructure.trace_context import validate_traceparent


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    id: str
    dedupe_key: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict[str, object]
    status: str
    attempt: int
    available_at: datetime
    created_at: datetime
    traceparent: str
    tracestate: str | None = None
    sent_at: datetime | None = None
    last_error: str | None = None


class Outbox:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        *,
        dedupe_key: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, object],
        traceparent: str,
        tracestate: str | None = None,
    ) -> OutboxMessage:
        validate_traceparent(traceparent)
        now = datetime.now(UTC)
        values = {
            "id": f"OUT-{uuid4().hex[:12].upper()}",
            "dedupe_key": dedupe_key,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "event_type": event_type,
            "payload": payload,
            "status": "pending",
            "attempt": 0,
            "available_at": now,
            "created_at": now,
            "traceparent": traceparent,
            "tracestate": tracestate,
        }
        dialect = self._session.get_bind().dialect.name
        if dialect == "sqlite":
            statement = sqlite_insert(OutboxMessageRow).values(**values)
            statement = statement.on_conflict_do_nothing(index_elements=["dedupe_key"])
        elif dialect == "mysql":
            statement = mysql_insert(OutboxMessageRow).values(**values).prefix_with("IGNORE")
        else:
            raise RuntimeError(f"不支持的数据库方言: {dialect}")
        await self._session.execute(statement)
        row = await self._session.scalar(
            select(OutboxMessageRow).where(OutboxMessageRow.dedupe_key == dedupe_key)
        )
        assert row is not None
        return _to_message(row)

    async def get(self, message_id: str) -> OutboxMessage | None:
        row = await self._session.scalar(
            select(OutboxMessageRow)
            .where(OutboxMessageRow.id == message_id)
            .with_for_update()
        )
        return None if row is None else _to_message(row)

    async def deliver(
        self,
        message_id: str,
        sender: Callable[[OutboxMessage], Awaitable[None]],
    ) -> OutboxMessage:
        row = await self._session.get(OutboxMessageRow, message_id)
        if row is None:
            raise LookupError("outbox_not_found")
        if row.status == "sent":
            return _to_message(row)
        row.attempt += 1
        try:
            await sender(_to_message(row))
        except Exception as error:
            row.last_error = type(error).__name__
            await self._session.flush()
            raise
        row.status = "sent"
        row.sent_at = datetime.now(UTC)
        row.last_error = None
        await self._session.flush()
        return _to_message(row)


def _to_message(row: OutboxMessageRow) -> OutboxMessage:
    return OutboxMessage(
        id=row.id,
        dedupe_key=row.dedupe_key,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        event_type=row.event_type,
        payload=dict(row.payload),
        status=row.status,
        attempt=row.attempt,
        available_at=ensure_utc(row.available_at),
        created_at=ensure_utc(row.created_at),
        sent_at=ensure_utc(row.sent_at),
        last_error=row.last_error,
        traceparent=row.traceparent,
        tracestate=row.tracestate,
    )
