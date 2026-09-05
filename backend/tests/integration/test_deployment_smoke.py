import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from serviceflow.api.app import create_app

ROOT = Path(__file__).parents[3]


def test_step10_delivery_files_are_present_and_scoped() -> None:
    required = (
        ".github/workflows/ci.yml",
        ".github/workflows/real-eval.yml",
        ".github/workflows/release.yml",
        "ops/otel/collector.yaml",
        "ops/prometheus/prometheus.yml",
        "ops/grafana/dashboards/serviceflow-overview.json",
        "ops/scripts/healthcheck.sh",
        "ops/scripts/deploy.sh",
        "ops/scripts/rollback.sh",
        "deploy/k8s/base/kustomization.yaml",
        "docs/public/DEPLOYMENT.md",
        "docs/public/OPERATIONS.md",
    )
    assert all((ROOT / path).is_file() for path in required)

    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    for service in (
        "mysql:",
        "redis:",
        "qdrant:",
        "api:",
        "gateway-a:",
        "gateway-b:",
        "worker:",
        "otel-collector:",
        "jaeger:",
        "prometheus:",
        "grafana:",
    ):
        assert f"  {service}" in compose
    assert "SERVICEFLOW_GATEWAY_QUEUE_LIMIT: 0" in compose
    assert "./ops/gateway-proxy/nginx.conf" in compose

    dashboard = json.loads(
        (ROOT / "ops/grafana/dashboards/serviceflow-overview.json").read_text(
            encoding="utf-8"
        )
    )
    assert dashboard["uid"] == "serviceflow-overview"


@pytest_asyncio.fixture
async def metrics_client(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'metrics.db').as_posix()}")
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    application = create_app(session_factory=factory)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await engine.dispose()


@pytest.mark.asyncio
async def test_api_exposes_low_cardinality_prometheus_metrics(metrics_client) -> None:
    response = await metrics_client.get("/metrics")

    assert response.status_code == 200
    assert "serviceflow_http_requests_total" in response.text
    assert "orderId" not in response.text
    assert "caseId" not in response.text
    assert "sessionId" not in response.text
