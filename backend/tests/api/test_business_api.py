from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from serviceflow.api.app import app
from serviceflow.api.dependencies import get_session
from serviceflow.infrastructure.database import Base


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    database_path = (tmp_path / "api.db").as_posix()
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def test_health_and_openapi_expose_business_routes(client: TestClient) -> None:
    assert client.get("/api/v1/health").json() == {"status": "ok"}

    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/health" in paths
    assert "/api/v1/orders/{order_id}" in paths
    assert "/api/v1/demo/reset" in paths
    assert "/api/v1/cases/{case_id}" in paths


def test_demo_reset_then_get_seeded_order(client: TestClient) -> None:
    reset_response = client.post("/api/v1/demo/reset")
    order_response = client.get("/api/v1/orders/ORDER-001")

    assert reset_response.status_code == 200
    assert reset_response.json() == {"users": 3, "orders": 12}
    assert order_response.status_code == 200
    assert order_response.json()["status"] == "paid"
    assert order_response.json()["total_amount"] == "199.00"


def test_missing_order_and_case_return_404(client: TestClient) -> None:
    assert client.get("/api/v1/orders/ORDER-404").status_code == 404
    assert client.get("/api/v1/cases/CASE-404").status_code == 404
