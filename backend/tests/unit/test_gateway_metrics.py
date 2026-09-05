from decimal import Decimal

import pytest

from serviceflow.infrastructure.gateway_metrics import GatewayMetrics
from serviceflow.infrastructure.model_gateway import GatewayCallRecord


def _record(*, model: str, fallback: str | None, latency: float) -> GatewayCallRecord:
    return GatewayCallRecord(
        route="operation-plan",
        route_version="step8-v1",
        primary_model="deepseek-v4-flash",
        selected_model=model,
        selected_provider="frontier-shared-domain",
        response_model=model,
        fallback_reason=fallback,
        attempt=2 if fallback else 1,
        input_tokens=100,
        output_tokens=20,
        cached_input_tokens=10,
        latency_ms=latency,
        ttft_ms=None,
        estimated_cost=Decimal("0.001000"),
        price_unit="frontier_diamond_per_million_tokens",
        capability_compatible=True,
        tenant_id="tenant-a",
        request_id=f"REQ-{model}",
    )


def test_metrics_collect_cost_latency_fallback_and_route_drift() -> None:
    metrics = GatewayMetrics()
    metrics.begin_request(route="operation-plan", risk_level="high")
    metrics.record(_record(model="deepseek-v4-flash", fallback=None, latency=10.0))
    metrics.begin_request(route="operation-plan", risk_level="high")
    metrics.record(
        _record(model="gpt-5.6-luna", fallback="rate_limit", latency=30.0)
    )

    route = metrics.snapshot()["routes"]["operation-plan"]
    assert route["requests_total"] == 2
    assert route["success_total"] == 2
    assert route["fallback_total"] == 1
    assert route["estimated_cost_total"] == "0.002000"
    assert route["latency_ms_avg"] == pytest.approx(20.0)
    assert route["latency_ms_p95"] == pytest.approx(30.0)

    drift = metrics.route_drift(
        route="operation-plan",
        baseline={"deepseek-v4-flash": 0.9, "gpt-5.6-luna": 0.1},
        quality_pass_rate=0.96,
        minimum_quality_pass_rate=0.95,
        shift_threshold=0.2,
    )
    assert drift.drifted is True
    assert drift.requires_model_ab is True
