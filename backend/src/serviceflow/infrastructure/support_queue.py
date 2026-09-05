from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.infrastructure.database import ensure_utc
from serviceflow.infrastructure.tables import SupportQueueRow


@dataclass(frozen=True, slots=True)
class HandoffRecord:
    id: str
    tenant_id: str
    user_id: str
    reason_code: str
    reason: str
    customer_message: str
    queue: str
    priority: str
    status: str
    context: dict[str, object]
    created_at: datetime
    session_id: str | None = None
    case_id: str | None = None
    trace_id: str | None = None
    resolved_at: datetime | None = None
    resolution: str | None = None


class SupportQueue:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, record: HandoffRecord) -> HandoffRecord:
        self._session.add(
            SupportQueueRow(
                id=record.id,
                tenant_id=record.tenant_id,
                user_id=record.user_id,
                session_id=record.session_id,
                case_id=record.case_id,
                trace_id=record.trace_id,
                reason_code=record.reason_code,
                reason=record.reason,
                customer_message=record.customer_message,
                queue=record.queue,
                priority=record.priority,
                status=record.status,
                context=record.context,
                created_at=record.created_at,
            )
        )
        await self._session.flush()
        return record

    async def get(self, handoff_id: str) -> HandoffRecord | None:
        row = await self._session.get(SupportQueueRow, handoff_id)
        return None if row is None else _to_record(row)


def _to_record(row: SupportQueueRow) -> HandoffRecord:
    return HandoffRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        session_id=row.session_id,
        case_id=row.case_id,
        trace_id=row.trace_id,
        reason_code=row.reason_code,
        reason=row.reason,
        customer_message=row.customer_message,
        queue=row.queue,
        priority=row.priority,
        status=row.status,
        context=dict(row.context or {}),
        created_at=ensure_utc(row.created_at),
        resolved_at=ensure_utc(row.resolved_at),
        resolution=row.resolution,
    )
