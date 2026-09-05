from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from serviceflow.infrastructure.audit_store import AuditStore, GatewayAuditWriter
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.model_gateway import GatewayCallRecord
from serviceflow.infrastructure.otel import Telemetry


@pytest.mark.asyncio
async def test_audit_is_persisted_when_trace_sampling_is_zero(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'audit.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    telemetry = Telemetry.in_memory(sample_ratio=0.0)

    with telemetry.span("request_refund"):
        async with factory() as session:
            await AuditStore(session).append(
                action="request_refund",
                tenant_id="tenant-a",
                actor="USER-001",
                operation_id="OP-001",
                parameter_summary={"argument_digest": "abc123"},
                result="confirmation_required",
            )
            await session.commit()

    async with factory() as session:
        records = await AuditStore(session).read_operation("OP-001")
    await engine.dispose()

    assert telemetry.finished_spans() == ()
    assert len(records) == 1
    assert records[0].payload["result"] == "confirmation_required"
    assert "prompt" not in records[0].payload


@pytest.mark.asyncio
async def test_gateway_audit_persists_business_and_trace_context(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'gateway.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    record = GatewayCallRecord(
        route="operation-plan",
        route_version="step8-v1",
        primary_model="deepseek-v4-flash",
        selected_model="gpt-5.6-luna",
        selected_provider="frontier-shared-domain",
        response_model="gpt-5.6-luna",
        fallback_reason="rate_limit",
        attempt=2,
        input_tokens=100,
        output_tokens=20,
        cached_input_tokens=10,
        latency_ms=12.0,
        ttft_ms=None,
        estimated_cost=Decimal("0.001000"),
        price_unit="frontier_diamond_per_million_tokens",
        capability_compatible=True,
        tenant_id="tenant-a",
        request_id="REQ-1",
        session_id="SESSION-1",
        goal_id="GOAL-1",
        case_id="CASE-1",
        operation_id="OP-1",
        run_id="RUN-1",
        trace_id="a" * 32,
    )

    await GatewayAuditWriter(factory)(record)

    async with factory() as session:
        records = await AuditStore(session).read_operation("OP-1")
    await engine.dispose()

    assert len(records) == 1
    stored = records[0]
    assert stored.tenant_id == "tenant-a"
    assert stored.session_id == "SESSION-1"
    assert stored.goal_id == "GOAL-1"
    assert stored.case_id == "CASE-1"
    assert stored.run_id == "RUN-1"
    assert stored.trace_id == "a" * 32
    assert stored.payload["request_id"] == "REQ-1"
