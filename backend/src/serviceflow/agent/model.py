import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from openai import AsyncOpenAI

from serviceflow.infrastructure.timing import measure_timing


class ModelConfigurationError(RuntimeError):
    pass


class ModelResponseError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ModelResult:
    content: dict[str, object]
    model: str
    input_tokens: int
    output_tokens: int


class StructuredModel(Protocol):
    async def complete_json(self, *, system: str, user: str) -> ModelResult: ...


class OpenAICompatibleModel:
    def __init__(
        self,
        *,
        client: Any,
        model: str,
        thinking_mode: str | None = None,
        reasoning_effort: str | None = None,
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
            ),
            model=model_name,
            thinking_mode=thinking_mode,
            reasoning_effort=reasoning_effort,
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
