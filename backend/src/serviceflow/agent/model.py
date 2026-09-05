import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from openai import AsyncOpenAI, OpenAIError

from serviceflow.infrastructure.timing import measure_timing


class ModelConfigurationError(RuntimeError):
    pass


class ModelResponseError(RuntimeError):
    pass


class NativeToolCallingUnavailable(ModelResponseError):
    pass


@dataclass(frozen=True, slots=True)
class ModelResult:
    content: dict[str, object]
    model: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class NativeToolCall:
    call_id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class NativeModelResult:
    content: str
    tool_calls: tuple[NativeToolCall, ...]
    model: str
    input_tokens: int
    output_tokens: int


class StructuredModel(Protocol):
    async def complete_json(self, *, system: str, user: str) -> ModelResult: ...


class NativeToolModel(Protocol):
    async def complete_with_tools(
        self,
        *,
        messages: Sequence[dict[str, object]],
        tools: Sequence[dict[str, object]],
    ) -> NativeModelResult: ...


class OpenAICompatibleModel:
    def __init__(
        self,
        *,
        client: Any,
        model: str,
        thinking_mode: str | None = None,
        reasoning_effort: str | None = None,
        forward_gateway_context: bool = False,
    ) -> None:
        if thinking_mode not in (None, "enabled", "disabled"):
            raise ModelConfigurationError("SERVICEFLOW_THINKING_MODE 只能是 enabled 或 disabled")
        if reasoning_effort not in (None, "low", "high", "max"):
            raise ModelConfigurationError(
                "SERVICEFLOW_REASONING_EFFORT 只能是 low、high 或 max"
            )
        self._client = client
        self._model = model
        self._thinking_mode = thinking_mode
        self._reasoning_effort = reasoning_effort
        self._forward_gateway_context = forward_gateway_context

    @classmethod
    def from_env(cls) -> "OpenAICompatibleModel":
        names = ("SERVICEFLOW_API_KEY", "SERVICEFLOW_BASE_URL", "SERVICEFLOW_MODEL")
        values = {}
        for name in names:
            values[name] = os.getenv(name)

        missing = []
        for name, value in values.items():
            if not value:
                missing.append(name)
        if missing:
            missing_names = ", ".join(missing)
            raise ModelConfigurationError(f"模型配置缺失：{missing_names}")

        model_name = values["SERVICEFLOW_MODEL"]
        if model_name is None:
            model_name = ""
        thinking_mode = os.getenv("SERVICEFLOW_THINKING_MODE")
        reasoning_effort = os.getenv("SERVICEFLOW_REASONING_EFFORT") or None
        return cls(
            client=AsyncOpenAI(
                api_key=values["SERVICEFLOW_API_KEY"],
                base_url=values["SERVICEFLOW_BASE_URL"],
                max_retries=0,
            ),
            model=model_name,
            thinking_mode=thinking_mode,
            reasoning_effort=reasoning_effort,
        )

    @classmethod
    def for_gateway(cls, *, base_url: str, model: str) -> "OpenAICompatibleModel":
        internal_key = os.getenv("SERVICEFLOW_GATEWAY_INTERNAL_KEY")
        if not internal_key:
            raise ModelConfigurationError("Gateway 配置缺少 SERVICEFLOW_GATEWAY_INTERNAL_KEY")
        return cls(
            client=AsyncOpenAI(api_key=internal_key, base_url=base_url),
            model=model,
            forward_gateway_context=True,
        )

    async def complete_json(self, *, system: str, user: str) -> ModelResult:
        request_options: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        if self._thinking_mode is not None:
            request_options["extra_body"] = {
                "thinking": {"type": self._thinking_mode},
            }
        if self._reasoning_effort is not None:
            request_options["reasoning_effort"] = self._reasoning_effort
        _add_trace_header(
            request_options, include_gateway_context=self._forward_gateway_context
        )
        with measure_timing("model_call_ms"):
            response = await self._client.chat.completions.create(**request_options)
        content = response.choices[0].message.content
        if not content:
            raise ModelResponseError("模型返回了空内容")
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ModelResponseError("模型返回的 JSON 必须是对象")
        usage = response.usage
        input_tokens = 0
        output_tokens = 0
        if usage is not None:
            input_tokens = usage.prompt_tokens
            output_tokens = usage.completion_tokens
        response_model = response.model
        if not response_model:
            response_model = self._model
        return ModelResult(
            content=parsed,
            model=response_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def complete_with_tools(
        self,
        *,
        messages: Sequence[dict[str, object]],
        tools: Sequence[dict[str, object]],
    ) -> NativeModelResult:
        return await self._complete_with_tools(messages=messages, tools=tools, route_name=None)

    async def complete_with_tools_for_route(
        self,
        *,
        route_name: str,
        messages: Sequence[dict[str, object]],
        tools: Sequence[dict[str, object]],
    ) -> NativeModelResult:
        return await self._complete_with_tools(
            messages=messages, tools=tools, route_name=route_name
        )

    async def _complete_with_tools(
        self,
        *,
        messages: Sequence[dict[str, object]],
        tools: Sequence[dict[str, object]],
        route_name: str | None,
    ) -> NativeModelResult:
        request_options: dict[str, Any] = {
            "model": self._model,
            "messages": list(messages),
            "tools": list(tools),
            "tool_choice": "auto",
        }
        if self._thinking_mode is not None:
            request_options["extra_body"] = {
                "thinking": {"type": self._thinking_mode},
            }
        if self._reasoning_effort is not None:
            request_options["reasoning_effort"] = self._reasoning_effort
        _add_trace_header(
            request_options, include_gateway_context=self._forward_gateway_context
        )
        if route_name is not None:
            headers = request_options.setdefault("extra_headers", {})
            headers["x-serviceflow-route"] = route_name
        with measure_timing("model_call_ms"):
            try:
                response = await self._client.chat.completions.create(**request_options)
            except OpenAIError as error:
                raise NativeToolCallingUnavailable("模型原生 Tool Calling 请求失败") from error
        if not response.choices:
            raise ModelResponseError("模型没有返回 choices")
        message = response.choices[0].message
        calls = []
        for call in message.tool_calls or ():
            function = getattr(call, "function", None)
            if function is None or not function.name:
                raise ModelResponseError("模型返回的 tool_call 缺少函数名")
            try:
                arguments = json.loads(function.arguments or "{}")
            except json.JSONDecodeError as error:
                raise ModelResponseError("模型返回的 tool_call 参数不是合法 JSON") from error
            if not isinstance(arguments, dict):
                raise ModelResponseError("模型返回的 tool_call 参数必须是 JSON 对象")
            calls.append(
                NativeToolCall(
                    call_id=str(call.id),
                    name=str(function.name),
                    arguments=arguments,
                )
            )
        usage = response.usage
        model_name = response.model or self._model
        return NativeModelResult(
            content=message.content or "",
            tool_calls=tuple(calls),
            model=model_name,
            input_tokens=usage.prompt_tokens if usage is not None else 0,
            output_tokens=usage.completion_tokens if usage is not None else 0,
        )


def _add_trace_header(
    request_options: dict[str, Any], *, include_gateway_context: bool = False
) -> None:
    headers = request_options.setdefault("extra_headers", {})
    from serviceflow.infrastructure.otel import current_traceparent

    try:
        traceparent = current_traceparent()
    except RuntimeError:
        traceparent = None
    if traceparent is not None:
        headers["traceparent"] = traceparent
    if include_gateway_context:
        from serviceflow.infrastructure.gateway_context import current_gateway_context

        headers.update(current_gateway_context().headers())
    if not headers:
        request_options.pop("extra_headers")
