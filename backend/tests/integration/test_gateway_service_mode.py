import httpx
import pytest

from serviceflow.agent.model import ModelResult, NativeModelResult, NativeToolCall
from serviceflow.infrastructure.gateway_context import current_gateway_context
from serviceflow.infrastructure.gateway_errors import GatewayErrorClass, GatewayFailure
from serviceflow.infrastructure.gateway_server import create_gateway_app
from serviceflow.infrastructure.otel import Telemetry


class StubGateway:
    def __init__(self) -> None:
        self.contexts = []

    async def complete_json(self, *, system: str, user: str) -> ModelResult:
        self.contexts.append(current_gateway_context())
        assert system == "json"
        assert user == "退款"
        return ModelResult({"intent": "refund"}, "deepseek-v4-flash", 10, 3)

    async def complete_with_tools(self, *, messages, tools) -> NativeModelResult:
        self.contexts.append(current_gateway_context())
        assert messages[-1]["content"] == "查订单"
        assert tools[0]["function"]["name"] == "get_order"
        return NativeModelResult(
            "",
            (NativeToolCall("call-1", "get_order", {"order_id": "ORDER-001"}),),
            "gpt-5.6-luna",
            12,
            4,
        )


@pytest.mark.asyncio
async def test_openai_compatible_gateway_service_preserves_json_and_tools() -> None:
    gateway = StubGateway()
    headers = {
        "Authorization": "Bearer test-gateway-key",
        "x-serviceflow-tenant-id": "tenant-a",
        "x-serviceflow-session-id": "SESSION-1",
        "x-serviceflow-run-id": "RUN-1",
    }
    telemetry = Telemetry.in_memory(sample_ratio=1)
    app = create_gateway_app(
        gateway, internal_key="test-gateway-key", telemetry=telemetry
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            structured = await client.post(
                "/v1/chat/completions",
                headers=headers,
                json={
                    "model": "route-default",
                    "messages": [
                        {"role": "system", "content": "json"},
                        {"role": "user", "content": "退款"},
                    ],
                    "response_format": {"type": "json_object"},
                },
            )
            native = await client.post(
                "/v1/chat/completions",
                headers=headers,
                json={
                    "model": "route-default",
                    "messages": [{"role": "user", "content": "查订单"}],
                    "tools": [
                        {"type": "function", "function": {"name": "get_order"}}
                    ],
                },
            )
            unauthorized = await client.get("/internal/traces")
            traces = await client.get("/internal/traces", headers=headers)
            streaming = await client.post(
                "/v1/chat/completions",
                headers=headers,
                json={"model": "route-default", "messages": [], "stream": True},
            )

    assert structured.status_code == 200
    assert structured.json()["choices"][0]["message"]["content"] == '{"intent":"refund"}'
    assert native.status_code == 200
    assert native.json()["model"] == "gpt-5.6-luna"
    assert native.json()["choices"][0]["message"]["tool_calls"][0]["function"][
        "name"
    ] == "get_order"
    assert unauthorized.status_code == 401
    assert streaming.status_code == 422
    assert {span["name"] for span in traces.json()["spans"]} == {"gateway.http"}
    assert {context.tenant_id for context in gateway.contexts} == {"tenant-a"}
    assert {context.session_id for context in gateway.contexts} == {"SESSION-1"}
    assert {context.run_id for context in gateway.contexts} == {"RUN-1"}
    telemetry.shutdown()


class FailingGateway:
    def __init__(self, error_class: GatewayErrorClass) -> None:
        self.error_class = error_class

    async def complete_json(self, *, system: str, user: str) -> ModelResult:
        del system, user
        raise GatewayFailure(self.error_class, "failed")


@pytest.mark.asyncio
async def test_gateway_maps_failures_to_actionable_http_statuses() -> None:
    headers = {
        "Authorization": "Bearer test-gateway-key",
        "x-serviceflow-tenant-id": "tenant-a",
    }
    cases = {
        GatewayErrorClass.BAD_REQUEST: 400,
        GatewayErrorClass.AUTHENTICATION: 401,
        GatewayErrorClass.PERMISSION: 403,
        GatewayErrorClass.INVALID_RESPONSE: 502,
        GatewayErrorClass.DEADLINE: 504,
        GatewayErrorClass.BACKPRESSURE: 503,
    }
    for error_class, expected in cases.items():
        app = create_gateway_app(
            FailingGateway(error_class), internal_key="test-gateway-key"
        )
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/v1/chat/completions",
                    headers=headers,
                    json={"messages": [{"role": "user", "content": "test"}]},
                )
        assert response.status_code == expected
