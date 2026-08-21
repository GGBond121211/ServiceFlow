from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from serviceflow.agent.model import ModelResult
from serviceflow.api.app import create_app
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.seed import seed_database


class ApiFakeModel:
    async def complete_json(self, *, system: str, user: str) -> ModelResult:
        responses: dict[str, dict[str, object]] = {
            "Cancel ORDER-001": {
                "order_id": "ORDER-001",
                "requested_action": "cancel",
                "issue_type": "none",
                "issue_summary": "Cancel before shipment",
                "missing_fields": [],
            },
            "Cancel my order": {
                "order_id": None,
                "requested_action": "cancel",
                "issue_type": "none",
                "issue_summary": "Cancel before shipment",
                "missing_fields": ["order_id"],
            },
            "The order is ORDER-001": {
                "order_id": "ORDER-001",
                "requested_action": None,
                "issue_type": "none",
                "issue_summary": "Provides the missing order",
                "missing_fields": ["requested_action"],
            },
            "Refund ORDER-003": {
                "order_id": "ORDER-003",
                "requested_action": "refund",
                "issue_type": "quality",
                "issue_summary": "Headphones are defective",
                "missing_fields": [],
            },
        }
        return ModelResult(
            content=responses[user],
            model="fake-api-model",
            input_tokens=10,
            output_tokens=5,
        )


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'agent-api.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        await seed_database(session)

    application = create_app(model=ApiFakeModel(), session_factory=factory)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as test_client:
        yield test_client
    await engine.dispose()


async def create_conversation(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/api/v1/conversations",
        json={"user_id": "USER-001"},
    )
    assert response.status_code == 201
    return response.json()["thread_id"]


@pytest.mark.asyncio
async def test_create_and_get_empty_conversation(client: httpx.AsyncClient) -> None:
    thread_id = await create_conversation(client)

    response = await client.get(f"/api/v1/conversations/{thread_id}")
    paths = (await client.get("/openapi.json")).json()["paths"]

    assert response.status_code == 200
    assert response.json() == {
        "thread_id": thread_id,
        "assistant_message": "",
        "decision": None,
        "policy_id": None,
        "tool_events": [],
        "final_business_state": {},
        "approval": None,
        "model": None,
        "prompt_version": None,
        "token_usage": {"input": 0, "output": 0},
    }
    assert "/api/v1/conversations" in paths
    assert "/api/v1/conversations/{thread_id}/messages" in paths
    assert "/api/v1/conversations/{thread_id}" in paths
    assert "/api/v1/conversations/{thread_id}/approvals/{approval_id}" in paths


@pytest.mark.asyncio
async def test_message_directly_processes_and_exposes_trace(
    client: httpx.AsyncClient,
) -> None:
    thread_id = await create_conversation(client)

    response = await client.post(
        f"/api/v1/conversations/{thread_id}/messages",
        json={"message": "Cancel ORDER-001"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "cancel"
    assert body["policy_id"] == "POL-CANCEL-01"
    actual_tools = []
    for event in body["tool_events"]:
        actual_tools.append(event["tool"])
    assert actual_tools == ["get_order", "cancel_order"]
    assert body["final_business_state"] == {"order_status": "cancelled"}
    assert body["model"] == "fake-api-model"
    assert body["prompt_version"] == "service_agent_v1"
    assert body["token_usage"] == {"input": 10, "output": 5}
    assert (await client.get(f"/api/v1/conversations/{thread_id}")).json() == body


@pytest.mark.asyncio
async def test_second_message_supplies_missing_order_in_same_thread(
    client: httpx.AsyncClient,
) -> None:
    thread_id = await create_conversation(client)

    missing = (
        await client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            json={"message": "Cancel my order"},
        )
    ).json()
    completed = (
        await client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            json={"message": "The order is ORDER-001"},
        )
    ).json()

    assert missing["decision"] == "ask_for_info"
    assert missing["tool_events"] == []
    assert "order_id" in missing["assistant_message"]
    assert completed["decision"] == "cancel"
    assert completed["final_business_state"] == {"order_status": "cancelled"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("approved", "approval_status", "order_status"),
    [(True, "approved", "refunded"), (False, "rejected", "delivered")],
)
async def test_approval_endpoint_resumes_approve_and_reject(
    client: httpx.AsyncClient,
    approved: bool,
    approval_status: str,
    order_status: str,
) -> None:
    thread_id = await create_conversation(client)
    pending = (
        await client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            json={"message": "Refund ORDER-003"},
        )
    ).json()

    assert pending["decision"] == "approval_required"
    assert pending["approval"]["status"] == "pending"
    approval_id = pending["approval"]["id"]

    response = await client.post(
        f"/api/v1/conversations/{thread_id}/approvals/{approval_id}",
        json={"approved": approved},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["approval"] == {"id": approval_id, "status": approval_status}
    assert body["final_business_state"]["order_status"] == order_status
    assert body["tool_events"][-1]["tool"] == "decide_approval"
    if approved:
        assert body["final_business_state"]["refund_status"] == "completed"
    else:
        assert "refund_status" not in body["final_business_state"]
