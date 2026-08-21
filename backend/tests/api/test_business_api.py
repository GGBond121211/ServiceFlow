from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from serviceflow.api.app import create_app
from serviceflow.infrastructure.database import Base


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    database_path = (tmp_path / "api.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    application = create_app(session_factory=session_factory)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as test_client:
        yield test_client
    await engine.dispose()


@pytest.mark.asyncio
async def test_health_and_openapi_expose_business_routes(
    client: httpx.AsyncClient,
) -> None:
    assert (await client.get("/api/v1/health")).json() == {"status": "ok"}

    paths = (await client.get("/openapi.json")).json()["paths"]
    assert "/api/v1/health" in paths
    assert "/api/v1/orders/{order_id}" in paths
    assert "/api/v1/demo/reset" in paths
    assert "/api/v1/cases/{case_id}" in paths


@pytest.mark.asyncio
async def test_demo_reset_then_get_seeded_order(client: httpx.AsyncClient) -> None:
    reset_response = await client.post("/api/v1/demo/reset")
    order_response = await client.get("/api/v1/orders/ORDER-001")

    assert reset_response.status_code == 200
    assert reset_response.json() == {"users": 3, "orders": 12}
    assert order_response.status_code == 200
    assert order_response.json()["status"] == "paid"
    assert order_response.json()["total_amount"] == "199.00"


@pytest.mark.asyncio
async def test_missing_order_and_case_return_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/orders/ORDER-404")).status_code == 404
    assert (await client.get("/api/v1/cases/CASE-404")).status_code == 404
