from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.domain.memory import MemoryRecord, MemoryScope, MemoryStatus
from serviceflow.infrastructure.database import ensure_utc
from serviceflow.infrastructure.tables import MemoryRow


class MemoryStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, record: MemoryRecord) -> MemoryRecord:
        row = MemoryRow(
            id=record.id,
            owner=record.owner,
            tenant_id=record.tenant_id,
            user_id=record.user_id,
            session_id=record.session_id,
            scope=record.scope.value,
            source=record.source,
            content=record.content,
            content_schema=record.content_schema,
            confidence=record.confidence,
            created_at=record.created_at,
            updated_at=record.updated_at,
            expires_at=record.expires_at,
            consent_status=record.consent_status,
            edit_status=record.edit_status,
            delete_status=record.delete_status,
            status=record.status.value,
        )
        self._session.add(row)
        await self._session.flush()
        return _to_domain(row)

    async def active_for(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str | None,
        now: datetime,
    ) -> tuple[MemoryRecord, ...]:
        rows = await self._session.scalars(
            select(MemoryRow)
            .where(
                MemoryRow.tenant_id == tenant_id,
                MemoryRow.user_id == user_id,
                MemoryRow.status == MemoryStatus.ACTIVE.value,
                (MemoryRow.session_id.is_(None) | (MemoryRow.session_id == session_id)),
                (MemoryRow.expires_at.is_(None) | (MemoryRow.expires_at > now)),
            )
            .order_by(MemoryRow.updated_at.desc(), MemoryRow.id)
        )
        return tuple(_to_domain(row) for row in rows)

    async def delete(self, *, memory_id: str, tenant_id: str, user_id: str) -> None:
        row = await self._session.get(MemoryRow, memory_id)
        if row is None or row.tenant_id != tenant_id or row.user_id != user_id:
            return
        row.status = MemoryStatus.DELETED.value
        row.delete_status = "deleted"
        await self._session.flush()


def new_memory_id() -> str:
    return f"MEM-{uuid4().hex[:20]}"


def _to_domain(row: MemoryRow) -> MemoryRecord:
    return MemoryRecord(
        id=row.id,
        owner=row.owner,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        session_id=row.session_id,
        scope=MemoryScope(row.scope),
        source=row.source,
        content=dict(row.content or {}),
        content_schema=dict(row.content_schema or {}),
        confidence=float(row.confidence),
        created_at=ensure_utc(row.created_at),
        updated_at=ensure_utc(row.updated_at),
        expires_at=ensure_utc(row.expires_at),
        consent_status=row.consent_status,
        edit_status=row.edit_status,
        delete_status=row.delete_status,
        status=MemoryStatus(row.status),
    )
