from pathlib import Path

import httpx
import pytest

from serviceflow.api.app import create_app


@pytest.mark.asyncio
async def test_local_frontend_origins_are_allowed() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_browser_demo_files_expose_required_sections() -> None:
    frontend = Path(__file__).parents[3] / "frontend"
    index = (frontend / "index.html").read_text(encoding="utf-8")

    assert (frontend / "app.js").is_file()
    assert (frontend / "styles.css").is_file()
    for marker in ("conversation", "order-status", "tool-timeline", "approval-actions"):
        assert marker in index


@pytest.mark.asyncio
async def test_evaluation_report_is_available_to_the_demo() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/evaluation/serviceflow-v1-report.md")

    assert response.status_code == 200
    assert "任务结果准确率" in response.text
