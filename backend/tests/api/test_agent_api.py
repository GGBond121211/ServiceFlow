from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from serviceflow.agent.model import ModelResult, NativeModelResult, NativeToolCall
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


class NativeApiFakeModel:
    async def complete_with_tools(self, *, messages, tools) -> NativeModelResult:
        return NativeModelResult(
            content="",
            tool_calls=(
                NativeToolCall(
                    "native-call-1",
                    "request_refund",
                    {"order_id": "ORDER-004"},
                ),
            ),
            model="fake-native-api-model",
            input_tokens=12,
            output_tokens=4,
        )


class NativeApprovalApiFakeModel:
    async def complete_with_tools(self, *, messages, tools) -> NativeModelResult:
        return NativeModelResult(
            content="",
            tool_calls=(
                NativeToolCall(
                    "native-approval-call-1",
                    "request_refund",
                    {"order_id": "ORDER-003"},
                ),
            ),
            model="fake-native-approval-model",
            input_tokens=12,
            output_tokens=4,
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


async def create_conversation(client: httpx.AsyncClient, user_id: str = "USER-001") -> str:
    response = await client.post(
        "/api/v1/conversations",
        json={"user_id": user_id},
    )
    assert response.status_code == 201
    return response.json()["thread_id"]


@pytest_asyncio.fixture
async def native_client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'native-agent-api.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        await seed_database(session)
    application = create_app(model=NativeApiFakeModel(), session_factory=factory)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    await engine.dispose()


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
        "agent_status": None,
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
    server_timing = response.headers["server-timing"]
    assert "graph_ms;dur=" in server_timing
    assert "database_connection_ms;dur=" in server_timing
    assert "database_phase_ms;dur=" in server_timing
    assert "policy_ms;dur=" in server_timing
    assert "response_build_ms;dur=" in server_timing
    assert "server_ms;dur=" in server_timing
    assert float(response.headers["x-serviceflow-server-ms"]) > 0
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
async def test_native_confirmation_resumes_the_pending_tool_and_reads_db(
    native_client: httpx.AsyncClient,
) -> None:
    thread_id = await create_conversation(native_client, user_id="USER-002")
    pending = (
        await native_client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            json={"message": "Refund ORDER-004"},
        )
    ).json()

    assert pending["agent_status"] == "WAITING_CONFIRMATION"
    assert pending["tool_events"][-1]["code"] == "confirmation_required"

    resumed = (
        await native_client.post(
            f"/api/v1/conversations/{thread_id}/confirmations",
            json={"confirmed": True},
        )
    ).json()

    assert resumed["agent_status"] == "COMPLETED"
    assert resumed["final_business_state"] == {
        "order_status": "refunded",
        "case_status": "completed",
    }
    assert resumed["tool_events"][-1]["code"] == "refund_completed"


@pytest.mark.asyncio
async def test_native_approval_endpoint_resumes_after_confirmation(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'native-approval-api.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        await seed_database(session)
    application = create_app(model=NativeApprovalApiFakeModel(), session_factory=factory)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        thread_id = await create_conversation(client)
        pending = (
            await client.post(
                f"/api/v1/conversations/{thread_id}/messages",
                json={"message": "Refund ORDER-003"},
            )
        ).json()
        confirmed = (
            await client.post(
                f"/api/v1/conversations/{thread_id}/confirmations",
                json={"confirmed": True},
            )
        ).json()
        approval_id = confirmed["approval"]["id"]
        approved = (
            await client.post(
                f"/api/v1/conversations/{thread_id}/approvals/{approval_id}",
                json={"approved": True},
            )
        ).json()
    await engine.dispose()

    assert pending["agent_status"] == "WAITING_CONFIRMATION"
    assert confirmed["agent_status"] == "WAITING_APPROVAL"
    assert confirmed["final_business_state"]["approval_status"] == "pending"
    assert approved["agent_status"] == "COMPLETED"
    assert approved["approval"] == {"id": approval_id, "status": "approved"}
    assert approved["final_business_state"] == {
        "order_status": "refunded",
        "approval_status": "approved",
        "refund_status": "completed",
    }


@pytest.mark.asyncio
async def test_native_confirmation_survives_api_app_restart(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'native-restart.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        await seed_database(session)

    first_app = create_app(model=NativeApiFakeModel(), session_factory=factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=first_app), base_url="http://testserver"
    ) as first:
        thread_id = await create_conversation(first, user_id="USER-002")
        pending = (
            await first.post(
                f"/api/v1/conversations/{thread_id}/messages",
                json={"message": "Refund ORDER-004"},
            )
        ).json()

    second_app = create_app(model=NativeApiFakeModel(), session_factory=factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=second_app), base_url="http://testserver"
    ) as second:
        restored = (await second.get(f"/api/v1/conversations/{thread_id}")).json()
        completed = (
            await second.post(
                f"/api/v1/conversations/{thread_id}/confirmations",
                json={"confirmed": True},
            )
        ).json()
    await engine.dispose()

    assert pending["agent_status"] == "WAITING_CONFIRMATION"
    assert restored["agent_status"] == "WAITING_CONFIRMATION"
    assert completed["agent_status"] == "COMPLETED"
    assert completed["final_business_state"]["order_status"] == "refunded"


@pytest.mark.asyncio
async def test_confirmation_rejects_tampered_pending_arguments(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'native-binding.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        await seed_database(session)
    application = create_app(model=NativeApiFakeModel(), session_factory=factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://testserver"
    ) as client:
        thread_id = await create_conversation(client, user_id="USER-002")
        await client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            json={"message": "Refund ORDER-004"},
        )
        graph = application.state.agent_graph
        state = (await graph.aget_state({"configurable": {"thread_id": thread_id}})).values
        pending = dict(state["pending_tool_call"])
        pending["arguments"] = {"order_id": "ORDER-007"}
        await graph.aupdate_state(
            {"configurable": {"thread_id": thread_id}},
            {"pending_tool_call": pending},
        )
        response = await client.post(
            f"/api/v1/conversations/{thread_id}/confirmations",
            json={"confirmed": True},
        )
    await engine.dispose()

    assert response.status_code == 409
    assert response.json()["detail"] == "pending_binding_mismatch"


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
