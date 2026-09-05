"""Event Log：业务事件的审计流水。

三条边界（计划补充 B）：这是业务事件不是应用日志；全量保留不参与 Trace 采样，
所以 append 没有 sampled 参数；只追加，刻意不提供 update / delete / purge。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.infrastructure.database import ensure_utc
from serviceflow.infrastructure.tables import EventLogRow

# 写成常量是为了让"不采样"在代码里有据可查，而不是只存在于文档里。
RETENTION = "full"


@dataclass(frozen=True, slots=True)
class EventRecord:
    seq: int
    event_type: str
    tenant_id: str
    actor: str
    recorded_at: datetime
    payload: dict[str, Any]
    session_id: str | None = None
    goal_id: str | None = None
    case_id: str | None = None
    operation_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None


class EventLog:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        event_type: str,
        tenant_id: str,
        actor: str,
        payload: Mapping[str, Any] | None = None,
        session_id: str | None = None,
        goal_id: str | None = None,
        case_id: str | None = None,
        operation_id: str | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
        at: datetime | None = None,
    ) -> EventRecord:
        row = EventLogRow(
            event_type=event_type,
            tenant_id=tenant_id,
            actor=actor,
            session_id=session_id,
            goal_id=goal_id,
            case_id=case_id,
            operation_id=operation_id,
            run_id=run_id,
            trace_id=trace_id,
            payload=dict(payload or {}),
            recorded_at=at or datetime.now(UTC),
        )
        self._session.add(row)
        await self._session.flush()
        return _to_record(row)

    async def read_case(self, case_id: str) -> tuple[EventRecord, ...]:
        return await self._read(EventLogRow.case_id == case_id)

    async def read_operation(self, operation_id: str) -> tuple[EventRecord, ...]:
        return await self._read(EventLogRow.operation_id == operation_id)

    async def read_session(self, session_id: str) -> tuple[EventRecord, ...]:
        return await self._read(EventLogRow.session_id == session_id)

    async def _read(self, condition: Any) -> tuple[EventRecord, ...]:
        rows = await self._session.scalars(
            select(EventLogRow).where(condition).order_by(EventLogRow.seq)
        )
        return tuple(_to_record(row) for row in rows)


def _to_record(row: EventLogRow) -> EventRecord:
    return EventRecord(
        seq=row.seq,
        event_type=row.event_type,
        tenant_id=row.tenant_id,
        actor=row.actor,
        recorded_at=ensure_utc(row.recorded_at),
        payload=dict(row.payload or {}),
        session_id=row.session_id,
        goal_id=row.goal_id,
        case_id=row.case_id,
        operation_id=row.operation_id,
        run_id=row.run_id,
        trace_id=row.trace_id,
    )
