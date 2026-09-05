import pytest

from serviceflow.infrastructure.metric_labels import metric_labels


def test_only_low_cardinality_labels_are_accepted() -> None:
    assert metric_labels(
        model="deepseek-v4-flash",
        provider="frontier",
        route="operation-plan",
        status="success",
        risk_level="high",
    ) == {
        "model": "deepseek-v4-flash",
        "provider": "frontier",
        "route": "operation-plan",
        "status": "success",
        "risk_level": "high",
    }


@pytest.mark.parametrize(
    "label",
    ["user_id", "tenant_id", "order_id", "session_id", "case_id", "prompt"],
)
def test_high_cardinality_or_sensitive_label_is_rejected(label: str) -> None:
    with pytest.raises(ValueError, match="Metrics"):
        metric_labels(**{label: "secret-or-unbounded"})
