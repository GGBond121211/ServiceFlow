from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from serviceflow.agent.model import StructuredModel
from serviceflow.domain.models import IssueType, RequestedAction

PROMPT_VERSION = "service_agent_v1"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt"


class ParsedIntent(BaseModel):
    order_id: str | None
    requested_action: RequestedAction | None
    issue_type: IssueType
    issue_summary: str
    missing_fields: list[str]


@dataclass(frozen=True, slots=True)
class IntentExtractionResult:
    intent: ParsedIntent | None
    error: str | None
    model_name: str
    prompt_version: str
    input_tokens: int
    output_tokens: int


class IntentExtractor:
    def __init__(self, model: StructuredModel) -> None:
        self._model = model
        self._prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def extract(self, user_message: str) -> IntentExtractionResult:
        model_result = self._model.complete_json(system=self._prompt, user=user_message)
        try:
            intent = ParsedIntent.model_validate(model_result.content)
        except ValidationError:
            return IntentExtractionResult(
                intent=None,
                error="intent_parse_error",
                model_name=model_result.model,
                prompt_version=PROMPT_VERSION,
                input_tokens=model_result.input_tokens,
                output_tokens=model_result.output_tokens,
            )
        return IntentExtractionResult(
            intent=intent,
            error=None,
            model_name=model_result.model,
            prompt_version=PROMPT_VERSION,
            input_tokens=model_result.input_tokens,
            output_tokens=model_result.output_tokens,
        )
