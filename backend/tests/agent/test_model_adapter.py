from types import SimpleNamespace

import pytest

import serviceflow.infrastructure.provider_model_adapters as provider_adapters
from serviceflow.agent.model import (
    ModelConfigurationError,
    OpenAICompatibleModel,
)


class FakeCompletions:
    def __init__(self) -> None:
        self.request: dict[str, object] | None = None

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.request = kwargs
        return SimpleNamespace(
            model="deepseek-v4-flash",
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"intent":"refund"}'))],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5),
        )


def test_missing_environment_returns_clear_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("SERVICEFLOW_API_KEY", "SERVICEFLOW_BASE_URL", "SERVICEFLOW_MODEL"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ModelConfigurationError, match="SERVICEFLOW_API_KEY"):
        OpenAICompatibleModel.from_env()


def test_environment_client_disables_sdk_implicit_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class CapturingClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("serviceflow.agent.model.AsyncOpenAI", CapturingClient)
    monkeypatch.setenv("SERVICEFLOW_API_KEY", "test-key")
    monkeypatch.setenv("SERVICEFLOW_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("SERVICEFLOW_MODEL", "test-model")

    OpenAICompatibleModel.from_env()

    assert captured["max_retries"] == 0


def test_provider_client_disables_sdk_implicit_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class CapturingClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(provider_adapters, "AsyncOpenAI", CapturingClient)

    provider_adapters.OpenAIModelProvider.from_credentials(
        "frontier", api_key="test-key", base_url="https://example.test/v1"
    )

    assert captured["max_retries"] == 0


@pytest.mark.asyncio
async def test_fake_client_json_maps_to_model_result() -> None:
    completions = FakeCompletions()
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    model = OpenAICompatibleModel(client=fake_client, model="deepseek-v4-flash")

    result = await model.complete_json(system="Return JSON", user="I want a refund")

    assert result.content == {"intent": "refund"}
    assert result.model == "deepseek-v4-flash"
    assert result.input_tokens == 12
    assert result.output_tokens == 5
    assert completions.request is not None
    assert completions.request["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_optional_thinking_mode_is_forwarded_to_deepseek() -> None:
    completions = FakeCompletions()
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    model = OpenAICompatibleModel(
        client=fake_client,
        model="deepseek-v4-flash",
        thinking_mode="enabled",
        reasoning_effort="low",
    )

    await model.complete_json(system="Return JSON", user="I want a refund")

    assert completions.request is not None
    assert completions.request["extra_body"] == {
        "thinking": {"type": "enabled"},
    }
    assert completions.request["reasoning_effort"] == "low"
