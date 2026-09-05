import json
from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)

from serviceflow.agent.model import NativeToolCall
from serviceflow.infrastructure.gateway_errors import GatewayErrorClass, GatewayFailure
from serviceflow.infrastructure.model_profiles import ModelProfile


@dataclass(frozen=True, slots=True)
class ProviderModelRequest:
    messages: Sequence[dict[str, object]]
    tools: Sequence[dict[str, object]]
    structured_output: bool
    timeout_seconds: float
    traceparent: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderModelResponse:
    content: str
    tool_calls: tuple[NativeToolCall, ...]
    response_model: str
    input_tokens: int
    output_tokens: int
    finish_reason: str
    latency_ms: float
    response_id: str | None = None
    ttft_ms: float | None = None
    cached_input_tokens: int = 0


class ModelProvider(Protocol):
    key: str

    async def complete(
        self, profile: ModelProfile, request: ProviderModelRequest
    ) -> ProviderModelResponse: ...


class OpenAIModelProvider:
    def __init__(self, key: str, *, client: Any) -> None:
        self.key = key
        self._client = client

    @classmethod
    def from_credentials(cls, key: str, *, api_key: str, base_url: str) -> "OpenAIModelProvider":
        return cls(
            key,
            client=AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0),
        )

    async def complete(
        self, profile: ModelProfile, request: ProviderModelRequest
    ) -> ProviderModelResponse:
        options: dict[str, object] = {
            "model": profile.model,
            "messages": list(request.messages),
            "timeout": request.timeout_seconds,
        }
        if request.tools:
            options.update({"tools": list(request.tools), "tool_choice": "auto"})
        if request.structured_output:
            options["response_format"] = {"type": "json_object"}
        if request.traceparent:
            options["extra_headers"] = {"traceparent": request.traceparent}
        started = perf_counter()
        try:
            response = await self._client.chat.completions.create(**options)
        except RateLimitError as error:
            raise GatewayFailure(GatewayErrorClass.RATE_LIMIT, "模型限流") from error
        except APITimeoutError as error:
            raise GatewayFailure(GatewayErrorClass.TIMEOUT, "模型调用超时") from error
        except APIConnectionError as error:
            raise GatewayFailure(GatewayErrorClass.CONNECTION, "模型连接失败") from error
        except AuthenticationError as error:
            raise GatewayFailure(GatewayErrorClass.AUTHENTICATION, "模型鉴权失败") from error
        except PermissionDeniedError as error:
            raise GatewayFailure(GatewayErrorClass.PERMISSION, "模型权限不足") from error
        except APIStatusError as error:
            error_class = _classify_http_status(error.status_code)
            raise GatewayFailure(error_class, f"模型 HTTP {error.status_code}") from error
        latency_ms = (perf_counter() - started) * 1000
        if not response.choices:
            raise GatewayFailure(GatewayErrorClass.INVALID_RESPONSE, "模型没有返回 choices")
        choice = response.choices[0]
        calls = []
        for call in choice.message.tool_calls or ():
            function = getattr(call, "function", None)
            if function is None or not function.name:
                raise GatewayFailure(GatewayErrorClass.INVALID_RESPONSE, "tool_call 缺少函数名")
            try:
                arguments = json.loads(function.arguments or "{}")
            except json.JSONDecodeError as error:
                raise GatewayFailure(
                    GatewayErrorClass.INVALID_RESPONSE, "tool_call 参数不是合法 JSON"
                ) from error
            if not isinstance(arguments, dict):
                raise GatewayFailure(
                    GatewayErrorClass.INVALID_RESPONSE, "tool_call 参数必须是 JSON 对象"
                )
            calls.append(NativeToolCall(str(call.id), str(function.name), arguments))
        usage = response.usage
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        return ProviderModelResponse(
            content=choice.message.content or "",
            tool_calls=tuple(calls),
            response_model=response.model or profile.model,
            input_tokens=usage.prompt_tokens if usage is not None else 0,
            output_tokens=usage.completion_tokens if usage is not None else 0,
            finish_reason=choice.finish_reason or "unknown",
            latency_ms=latency_ms,
            response_id=getattr(response, "id", None),
            cached_input_tokens=(
                getattr(prompt_details, "cached_tokens", 0) or 0
                if prompt_details is not None
                else 0
            ),
        )


def _classify_http_status(status_code: int) -> GatewayErrorClass:
    if status_code == 429:
        return GatewayErrorClass.RATE_LIMIT
    if status_code >= 500:
        return GatewayErrorClass.SERVER_ERROR
    return GatewayErrorClass.BAD_REQUEST
