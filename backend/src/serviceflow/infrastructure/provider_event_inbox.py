from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from serviceflow.domain.operations import ErrorClass, OperationStatus
from serviceflow.infrastructure.case_repository import AfterSalesCaseStore, OperationStore
from serviceflow.infrastructure.event_log import EventLog
from serviceflow.infrastructure.outbox import Outbox
from serviceflow.infrastructure.provider_adapters import ProviderStatus
from serviceflow.infrastructure.tables import ProviderEventInboxRow


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    provider: str
    event_id: str
    event_type: str
    operation_id: str
    payload: dict[str, object]
    traceparent: str


class ProviderEventInbox:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, event: ProviderEvent) -> bool:
        values = {
            "provider": event.provider,
            "event_id": event.event_id,
            "event_type": event.event_type,
            "operation_id": event.operation_id,
            "payload": event.payload,
            "traceparent": event.traceparent,
            "received_at": datetime.now(UTC),
        }
        dialect = self._session.get_bind().dialect.name
        if dialect == "sqlite":
            statement = sqlite_insert(ProviderEventInboxRow).values(**values)
            statement = statement.on_conflict_do_nothing(index_elements=["provider", "event_id"])
        elif dialect == "mysql":
            statement = mysql_insert(ProviderEventInboxRow).values(**values).prefix_with("IGNORE")
        else:
            raise RuntimeError(f"不支持的数据库方言: {dialect}")
        result = await self._session.execute(statement)
        return result.rowcount == 1

    async def mark_processed(self, event: ProviderEvent, *, at: datetime) -> None:
        row = await self._session.scalar(
            select(ProviderEventInboxRow).where(
                ProviderEventInboxRow.provider == event.provider,
                ProviderEventInboxRow.event_id == event.event_id,
            )
        )
        if row is None:
            raise LookupError("provider_event_not_found")
        row.processed_at = at
        await self._session.flush()


class ProviderEventProcessor:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def apply(self, event: ProviderEvent, status: ProviderStatus) -> bool:
        now = datetime.now(UTC)
        async with self._session_factory() as db:
            inbox = ProviderEventInbox(db)
            if not await inbox.record(event):
                await db.commit()
                return False
            operation = await OperationStore(db).get(event.operation_id)
            if operation is None:
                raise LookupError("operation_not_found")
            target = {
                ProviderStatus.PENDING: OperationStatus.PENDING,
                ProviderStatus.SUCCEEDED: OperationStatus.SUCCEEDED,
                ProviderStatus.FAILED: OperationStatus.FAILED,
                ProviderStatus.UNKNOWN: OperationStatus.UNKNOWN,
            }[status]
            updated = await OperationStore(db).finish(
                operation.id,
                status=target,
                at=now,
                result_code=f"webhook_{status.value}",
                error_class=(
                    ErrorClass.NONE
                    if status is not ProviderStatus.FAILED
                    else ErrorClass.PROVIDER_ERROR
                ),
            )
            if status is ProviderStatus.SUCCEEDED:
                await Outbox(db).enqueue(
                    dedupe_key=f"operation-completed:{updated.id}",
                    aggregate_type="operation",
                    aggregate_id=updated.id,
                    event_type="operation_completed",
                    payload={"operation_id": updated.id, "source": "webhook"},
                    traceparent=event.traceparent,
                )
            case = await AfterSalesCaseStore(db).get(updated.case_id)
            await EventLog(db).append(
                event_type="provider_webhook_applied",
                tenant_id=case.tenant_id if case else "unknown",
                actor="provider",
                goal_id=case.goal_id if case else None,
                case_id=updated.case_id,
                operation_id=updated.id,
                trace_id=event.traceparent.split("-")[1],
                payload={
                    "provider": event.provider,
                    "event_id": event.event_id,
                    "status": status.value,
                },
                at=now,
            )
            await inbox.mark_processed(event, at=now)
            await db.commit()
        return True
