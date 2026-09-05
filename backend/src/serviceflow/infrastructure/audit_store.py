from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from serviceflow.infrastructure.event_log import EventLog, EventRecord
from serviceflow.infrastructure.model_gateway import GatewayCallRecord


class AuditStore:
    def __init__(self, session: AsyncSession) -> None:
        self._events = EventLog(session)

    async def append(
        self,
        *,
        action: str,
        tenant_id: str,
        actor: str,
        parameter_summary: Mapping[str, object],
        result: str,
        session_id: str | None = None,
        goal_id: str | None = None,
        case_id: str | None = None,
        operation_id: str | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
    ) -> EventRecord:
        return await self._events.append(
            event_type=action,
            tenant_id=tenant_id,
            actor=actor,
            session_id=session_id,
            goal_id=goal_id,
            case_id=case_id,
            operation_id=operation_id,
            run_id=run_id,
            trace_id=trace_id,
            payload={**dict(parameter_summary), "result": result},
        )

    async def read_operation(self, operation_id: str) -> tuple[EventRecord, ...]:
        return await self._events.read_operation(operation_id)


class GatewayAuditWriter:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __call__(self, record: GatewayCallRecord) -> None:
        async with self._session_factory() as session:
            await AuditStore(session).append(
                action="gateway_model_call",
                tenant_id=record.tenant_id,
                actor="gateway",
                parameter_summary={
                    "request_id": record.request_id,
                    "route": record.route,
                    "route_version": record.route_version,
                    "primary_model": record.primary_model,
                    "selected_model": record.selected_model,
                    "selected_provider": record.selected_provider,
                    "response_model": record.response_model,
                    "fallback_reason": record.fallback_reason,
                    "attempt": record.attempt,
                    "input_tokens": record.input_tokens,
                    "output_tokens": record.output_tokens,
                    "cached_input_tokens": record.cached_input_tokens,
                    "latency_ms": round(record.latency_ms, 3),
                    "ttft_ms": record.ttft_ms,
                    "estimated_cost": (
                        str(record.estimated_cost) if record.estimated_cost is not None else None
                    ),
                    "price_unit": record.price_unit,
                    "capability_compatible": record.capability_compatible,
                    "status": record.status,
                    "error_class": record.error_class,
                    "metric_labels": record.metric_labels,
                },
                result=record.status,
                session_id=record.session_id,
                goal_id=record.goal_id,
                case_id=record.case_id,
                operation_id=record.operation_id,
                run_id=record.run_id,
                trace_id=record.trace_id,
            )
            await session.commit()
