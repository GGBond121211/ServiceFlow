import asyncio
import os

from celery import Celery

from serviceflow.api.dependencies import SessionFactory
from serviceflow.infrastructure.event_log import EventLog
from serviceflow.infrastructure.otel import Telemetry
from serviceflow.infrastructure.outbox import Outbox, OutboxMessage

telemetry = Telemetry.from_env(
    sample_ratio=float(os.getenv("SERVICEFLOW_TRACE_SAMPLE_RATIO", "1"))
)

celery_app = Celery(
    "serviceflow",
    broker=os.getenv("SERVICEFLOW_CELERY_BROKER_URL", "redis://localhost:6379/1"),
    backend=os.getenv("SERVICEFLOW_CELERY_RESULT_BACKEND", "redis://localhost:6379/2"),
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


@celery_app.task(name="serviceflow.deliver_outbox", bind=True, max_retries=3)
def deliver_outbox(self, message_id: str) -> dict[str, object]:
    try:
        return asyncio.run(_deliver_outbox(message_id))
    except Exception as error:
        raise self.retry(exc=error, countdown=min(2 ** self.request.retries, 30)) from error


async def _deliver_outbox(message_id: str) -> dict[str, object]:
    async with SessionFactory() as session:
        current = await Outbox(session).get(message_id)
        if current is None:
            raise LookupError("outbox_not_found")

        async def record_delivery(message: OutboxMessage) -> None:
            await EventLog(session).append(
                event_type="outbox_delivered",
                tenant_id="default",
                actor="worker",
                operation_id=(
                    message.aggregate_id if message.aggregate_type == "operation" else None
                ),
                trace_id=message.traceparent.split("-")[1],
                payload={"message_id": message.id, "event_type": message.event_type},
            )

        with telemetry.span("worker.outbox", traceparent=current.traceparent):
            with telemetry.span("outbox.deliver"):
                try:
                    delivered = await Outbox(session).deliver(message_id, record_delivery)
                    await session.commit()
                except Exception:
                    await session.commit()
                    raise
    return {
        "message_id": delivered.id,
        "status": delivered.status,
        "attempt": delivered.attempt,
        "traceparent": delivered.traceparent,
    }
