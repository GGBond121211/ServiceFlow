import asyncio
from collections import deque
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from serviceflow.agent.model import NativeToolCall
from serviceflow.agent.worker_tasks import _deliver_outbox
from serviceflow.api.app import create_app
from serviceflow.domain.policy_documents import PolicyDocument
from serviceflow.infrastructure.model_gateway import ModelGateway
from serviceflow.infrastructure.model_profiles import ModelProfile, ModelRegistry, RouteProfile
from serviceflow.infrastructure.otel import Telemetry
from serviceflow.infrastructure.outbox import Outbox
from serviceflow.infrastructure.provider_model_adapters import (
    ProviderModelRequest,
    ProviderModelResponse,
)
from serviceflow.infrastructure.qdrant_policy_store import ExactPolicyStore, PolicyRetriever
from serviceflow.infrastructure.trace_context import trace_id_from_traceparent


class TraceProvider:
    key = "frontier-primary"

    def __init__(self) -> None:
        self.responses = deque(
            [
                ProviderModelResponse(
                    content="",
                    tool_calls=(
                        NativeToolCall("call-1", "get_order", {"order_id": "ORDER-001"}),
                    ),
                    response_model="deepseek-v4-flash",
                    input_tokens=10,
                    output_tokens=3,
                    finish_reason="tool_calls",
                    latency_ms=4.0,
                ),
                ProviderModelResponse(
                    content="订单状态已从数据库核验。",
                    tool_calls=(),
                    response_model="deepseek-v4-flash",
                    input_tokens=12,
                    output_tokens=4,
                    finish_reason="stop",
                    latency_ms=5.0,
                ),
            ]
        )

    async def complete(
        self, profile: ModelProfile, request: ProviderModelRequest
    ) -> ProviderModelResponse:
        del profile, request
        return self.responses.popleft()


def _trace_gateway(telemetry: Telemetry) -> ModelGateway:
    model = ModelProfile(
        key="frontier-primary",
        provider="frontier-shared-domain",
        model="deepseek-v4-flash",
        context_length=1_000_000,
        native_tool_calling=True,
        structured_output="json_mode",
        chinese_after_sales=True,
        input_cost_per_million=Decimal("12"),
        output_cost_per_million=Decimal("36"),
        cached_input_cost_per_million=Decimal("0.3996"),
        price_unit="frontier_diamond_per_million_tokens",
        priced_at="2026-09-05",
        price_source="test",
    )
    routes = tuple(
        RouteProfile(
            name=name,
            version="step8.1-v1",
            candidates=(model.key,),
            required_capabilities=("native_tool_calling", "chinese_after_sales"),
            max_attempts_per_model=1,
            deadline_seconds=2,
            risk_level="low",
        )
        for name in ("operation-plan", "final-response")
    )
    provider = TraceProvider()
    return ModelGateway(
        ModelRegistry(models=(model,), routes=routes),
        {provider.key: provider},
        telemetry=telemetry,
    )


@pytest.mark.asyncio
async def test_http_gateway_tool_provider_worker_share_one_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    telemetry = Telemetry.in_memory(sample_ratio=1.0)
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'trace.db').as_posix()}")
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(
        model=_trace_gateway(telemetry),
        session_factory=factory,
        telemetry=telemetry,
    )
    monkeypatch.setenv("SERVICEFLOW_MCP_TRANSPORT", "in_process")

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.post("/api/v1/demo/reset")).status_code == 200
            conversation = await client.post(
                "/api/v1/conversations", json={"user_id": "USER-001"}
            )
            thread_id = conversation.json()["thread_id"]
            response = await client.post(
                f"/api/v1/conversations/{thread_id}/messages",
                json={"message": "查询 ORDER-001"},
            )
            assert response.status_code == 200
            api_traceparent = response.headers["traceparent"]

        with telemetry.span("outbox.enqueue", traceparent=api_traceparent):
            outbox_traceparent = telemetry.current_traceparent()
            async with factory() as session:
                message = await Outbox(session).enqueue(
                    dedupe_key="trace-chain",
                    aggregate_type="operation",
                    aggregate_id="OP-TRACE",
                    event_type="provider_reconcile",
                    payload={"operation_id": "OP-TRACE"},
                    traceparent=outbox_traceparent,
                )
                await session.commit()

        import serviceflow.agent.worker_tasks as worker_tasks

        monkeypatch.setattr(worker_tasks, "SessionFactory", factory)
        monkeypatch.setattr(worker_tasks, "telemetry", telemetry)
        await _deliver_outbox(message.id)

    target_trace_id = trace_id_from_traceparent(api_traceparent)
    spans = tuple(
        span
        for span in telemetry.finished_spans()
        if format(span.context.trace_id, "032x") == target_trace_id
    )
    assert {
        "http.request",
        "gateway.route",
        "gen_ai.chat",
        "tool.call",
        "outbox.enqueue",
        "worker.outbox",
        "outbox.deliver",
    }.issubset({span.name for span in spans})
    assert {format(span.context.trace_id, "032x") for span in spans} == {target_trace_id}
    outbox = next(span for span in spans if span.name == "outbox.enqueue")
    worker = next(span for span in spans if span.name == "worker.outbox")
    assert worker.parent.span_id == outbox.context.span_id
    await engine.dispose()


def test_manual_span_contract_is_still_available_for_unit_diagnostics() -> None:
    telemetry = Telemetry.in_memory(sample_ratio=1.0)
    with telemetry.span("http.request"):
        traceparent = telemetry.current_traceparent()
        with telemetry.span("gateway.route"):
            pass
    with telemetry.span("worker.outbox", traceparent=traceparent):
        pass
    spans = telemetry.finished_spans()
    assert {span.name for span in spans} == {
        "http.request",
        "gateway.route",
        "worker.outbox",
    }


def test_rag_trace_records_recall_rerank_and_prompt_sets() -> None:
    document = PolicyDocument(
        policy_id="POL-1",
        version="v1",
        title="退款",
        content="质量问题可以申请退款",
        source_title="test",
        source_url="https://example.invalid",
        source_locator="1",
        source_hash="a" * 64,
        tenant_id="default",
        region="CN",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        source_type="test",
    )
    telemetry = Telemetry.in_memory(sample_ratio=1.0)
    retriever = PolicyRetriever(ExactPolicyStore((document,)), telemetry=telemetry)

    async def run() -> None:
        with telemetry.span("http.request"):
            evidence, _, _ = await retriever.retrieve(
                "退款",
                tenant_id="default",
                region="CN",
                at=date(2026, 9, 5),
            )
            retriever.trace_prompt_ids([item.document.policy_id for item in evidence])

    asyncio.run(run())
    attributes = {span.name: dict(span.attributes) for span in telemetry.finished_spans()}
    retrieval = attributes["retrieval.policy"]
    prompt = attributes["context.policy_evidence"]
    assert retrieval["serviceflow.retrieval.recalled_ids"] == ("POL-1",)
    assert retrieval["serviceflow.retrieval.reranked_ids"] == ("POL-1",)
    assert prompt["serviceflow.retrieval.prompt_ids"] == ("POL-1",)
