from dataclasses import dataclass

import pytest

from serviceflow.agent.intent import IntentExtractor
from serviceflow.agent.model import ModelResult
from serviceflow.domain.models import IssueType, RequestedAction


@dataclass
class StubModel:
    content: dict[str, object]

    def complete_json(self, *, system: str, user: str) -> ModelResult:
        assert "requested_action" in system
        assert user
        return ModelResult(
            content=self.content,
            model="fake-intent-model",
            input_tokens=11,
            output_tokens=7,
        )


@pytest.mark.parametrize(
    ("content", "expected_order", "expected_action", "expected_issue"),
    [
        (
            {
                "order_id": "ORDER-001",
                "requested_action": "cancel",
                "issue_type": "none",
                "issue_summary": "Cancel before shipment",
                "missing_fields": [],
            },
            "ORDER-001",
            RequestedAction.CANCEL,
            IssueType.NONE,
        ),
        (
            {
                "order_id": "ORDER-003",
                "requested_action": "refund",
                "issue_type": "quality",
                "issue_summary": "Left earbud has no sound",
                "missing_fields": [],
            },
            "ORDER-003",
            RequestedAction.REFUND,
            IssueType.QUALITY,
        ),
        (
            {
                "order_id": None,
                "requested_action": "refund",
                "issue_type": "quality",
                "issue_summary": "Headphones are broken",
                "missing_fields": ["order_id"],
            },
            None,
            RequestedAction.REFUND,
            IssueType.QUALITY,
        ),
        (
            {
                "order_id": "ORDER-002",
                "requested_action": "query",
                "issue_type": "none",
                "issue_summary": "Check order status",
                "missing_fields": [],
            },
            "ORDER-002",
            RequestedAction.QUERY,
            IssueType.NONE,
        ),
    ],
)
def test_extracts_supported_intents(
    content: dict[str, object],
    expected_order: str | None,
    expected_action: RequestedAction,
    expected_issue: IssueType,
) -> None:
    result = IntentExtractor(StubModel(content)).extract("demo message")

    assert result.error is None
    assert result.intent is not None
    assert result.intent.order_id == expected_order
    assert result.intent.requested_action is expected_action
    assert result.intent.issue_type is expected_issue
    assert result.model_name == "fake-intent-model"
    assert result.prompt_version == "service_agent_v1"
    assert result.input_tokens == 11
    assert result.output_tokens == 7


def test_invalid_model_output_returns_parse_error_without_retry() -> None:
    model = StubModel({"requested_action": "unsupported"})

    result = IntentExtractor(model).extract("do something")

    assert result.intent is None
    assert result.error == "intent_parse_error"
