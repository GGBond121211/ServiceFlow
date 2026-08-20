from types import SimpleNamespace

import pytest

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
