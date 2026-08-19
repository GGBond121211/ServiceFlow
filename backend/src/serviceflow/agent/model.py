import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from openai import OpenAI


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
    def complete_json(self, *, system: str, user: str) -> ModelResult: ...


class OpenAICompatibleModel:
    def __init__(self, *, client: Any, model: str) -> None:
        self._client = client
        self._model = model

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
        return cls(
            client=OpenAI(
                api_key=values["SERVICEFLOW_API_KEY"],
                base_url=values["SERVICEFLOW_BASE_URL"],
            ),
            model=model_name,
        )

    def complete_json(self, *, system: str, user: str) -> ModelResult:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
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
