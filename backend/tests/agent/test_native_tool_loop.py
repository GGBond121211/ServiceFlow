from types import SimpleNamespace

import pytest

from serviceflow.agent.model import (
    NativeModelResult,
    NativeToolCall,
    OpenAICompatibleModel,
)
from serviceflow.agent.tool_loop import ToolLoop, ToolLoopConfig
from serviceflow.agent.tool_registry import ToolRegistry
from serviceflow.infrastructure.gateway_context import bind_gateway_context
from serviceflow.infrastructure.otel import Telemetry


class SequencedModel:
    def __init__(self) -> None:
        self.requests: list[list[dict[str, object]]] = []
        self._responses = [
            NativeModelResult(
                content="",
                tool_calls=(NativeToolCall("call-1", "get_order", {"order_id": "ORDER-001"}),),
                model="fake-native-model",
                input_tokens=10,
                output_tokens=3,
            ),
            NativeModelResult(
                content="订单已查到，我继续查询退款估算。",
                tool_calls=(
                    NativeToolCall("call-2", "estimate_refund", {"order_id": "ORDER-001"}),
                ),
                model="fake-native-model",
                input_tokens=11,
                output_tokens=3,
            ),
            NativeModelResult(
                content="订单实付金额为 199 元。",
                tool_calls=(),
                model="fake-native-model",
                input_tokens=12,
                output_tokens=4,
            ),
        ]

    async def complete_with_tools(self, *, messages, tools):
        self.requests.append(list(messages))
        return self._responses.pop(0)


class FakeHost:
    async def discover_tools(self):
        return ToolRegistry.default().discover()

    async def discover_resources(self):
        return ({"uri": "serviceflow://policy/current"},)

    async def discover_prompts(self):
        return ({"name": "operation_planning"},)

    async def call_tool(self, *, call_id, name, arguments, context):
        if name == "get_order":
            return {
                "tool_call_id": call_id,
                "tool_name": name,
                "ok": True,
                "code": "ok",
                "data": {"status": "delivered"},
            }
        return {
            "tool_call_id": call_id,
            "tool_name": name,
            "ok": True,
            "code": "ok",
            "data": {"amount": "199.00"},
        }


@pytest.mark.asyncio
async def test_tool_result_changes_the_next_model_turn() -> None:
    model = SequencedModel()
    result = await ToolLoop(model=model, host=FakeHost()).run(
        user_message="帮我查询订单并估算退款",
        user_id="USER-001",
        tenant_id="tenant-a",
    )

    assert result.status == "COMPLETED"
    assert result.message == "订单实付金额为 199 元。"
    assert [event["tool"] for event in result.tool_events] == ["get_order", "estimate_refund"]
    assert len(model.requests) == 3
    assert "delivered" in str(model.requests[1])


@pytest.mark.asyncio
async def test_repeated_identical_tool_call_stops_loop() -> None:
    class RepeatingModel(SequencedModel):
        def __init__(self) -> None:
            super().__init__()
            self._responses = [self._responses[0], self._responses[0]]

    result = await ToolLoop(
        model=RepeatingModel(),
        host=FakeHost(),
        config=ToolLoopConfig(max_steps=5),
    ).run(user_message="查询订单", user_id="USER-001", tenant_id="tenant-a")

    assert result.status == "STUCK"
    assert "重复" in result.message


@pytest.mark.asyncio
async def test_native_history_is_bounded_and_not_a_source_of_business_facts() -> None:
    model = SequencedModel()
    history = [{"role": "user", "content": f"历史-{index}"} for index in range(12)]
    await ToolLoop(model=model, host=FakeHost()).run(
        user_message="那笔订单", user_id="USER-001", tenant_id="tenant-a", history=history
    )
    first = model.requests[0]
    assert first[1:-1] == history[-8:]
    assert first[-1]["content"] == "那笔订单"
    assert "必须重新查工具" in first[0]["content"]


@pytest.mark.asyncio
async def test_openai_compatible_model_parses_native_tool_calls() -> None:
    class Completions:
        async def create(self, **kwargs):
            return SimpleNamespace(
                model="deepseek-v4-flash",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    id="call-1",
                                    function=SimpleNamespace(
                                        name="get_order",
                                        arguments='{"order_id":"ORDER-001"}',
                                    ),
                                )
                            ],
                        )
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=20, completion_tokens=8),
            )

    model = OpenAICompatibleModel(
        client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())),
        model="deepseek-v4-flash",
    )
    result = await model.complete_with_tools(messages=[], tools=[])

    assert result.tool_calls[0].name == "get_order"
    assert result.tool_calls[0].arguments == {"order_id": "ORDER-001"}


@pytest.mark.asyncio
async def test_gateway_client_forwards_trace_and_business_context_headers() -> None:
    class Completions:
        def __init__(self) -> None:
            self.options = None

        async def create(self, **kwargs):
            self.options = kwargs
            return SimpleNamespace(
                model="deepseek-v4-flash",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="完成", tool_calls=[])
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1),
            )

    completions = Completions()
    model = OpenAICompatibleModel(
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        model="deepseek-v4-flash",
        forward_gateway_context=True,
    )
    telemetry = Telemetry.in_memory(sample_ratio=1.0)
    with telemetry.span("http.request"):
        with bind_gateway_context(
            tenant_id="tenant-a",
            session_id="SESSION-1",
            case_id="CASE-1",
            operation_id="OP-1",
            run_id="RUN-1",
        ):
            await model.complete_with_tools(messages=[], tools=[])

    headers = completions.options["extra_headers"]
    assert headers["traceparent"].startswith("00-")
    assert headers["x-serviceflow-tenant-id"] == "tenant-a"
    assert headers["x-serviceflow-session-id"] == "SESSION-1"
    assert headers["x-serviceflow-case-id"] == "CASE-1"
    assert headers["x-serviceflow-operation-id"] == "OP-1"
    assert headers["x-serviceflow-run-id"] == "RUN-1"


@pytest.mark.asyncio
async def test_completed_high_risk_tool_uses_high_risk_review_route() -> None:
    class RoutedModel:
        def __init__(self) -> None:
            self.routes = []
            self.responses = [
                NativeModelResult(
                    "",
                    (
                        NativeToolCall(
                            "call-1", "request_refund", {"order_id": "ORDER-001"}
                        ),
                    ),
                    "primary",
                    10,
                    3,
                ),
                NativeModelResult("退款结果已复核。", (), "primary", 8, 2),
            ]

        async def complete_with_tools_for_route(self, *, route_name, messages, tools):
            del messages, tools
            self.routes.append(route_name)
            return self.responses.pop(0)

        async def complete_with_tools(self, *, messages, tools):
            raise AssertionError("必须使用版本化 route")

    class HighRiskHost(FakeHost):
        async def call_tool(self, *, call_id, name, arguments, context):
            del arguments
            assert context["confirmed"] is True
            assert context["approval_granted"] is True
            return {
                "tool_call_id": call_id,
                "tool_name": name,
                "ok": True,
                "code": "ok",
                "data": {"case_id": "CASE-1", "operation_id": "OP-1"},
            }

    model = RoutedModel()
    result = await ToolLoop(model=model, host=HighRiskHost()).run(
        user_message="执行已确认并审批的退款",
        user_id="USER-001",
        tenant_id="tenant-a",
        confirmed=True,
        approval_granted=True,
        session_id="SESSION-1",
        run_id="RUN-1",
    )

    assert result.status == "COMPLETED"
    assert model.routes == ["operation-plan", "high-risk-review"]
