import pytest

from serviceflow.agent.context_budget import (
    ContextBudget,
    ContextBudgetExceeded,
    ContextSection,
    build_context,
)


def test_budget_drops_low_priority_sections_as_whole_blocks() -> None:
    result = build_context(
        (
            ContextSection("identity", "tenant-a/user-1", priority=100, required=True),
            ContextSection("current_case", "金额=899, status=pending", priority=100, required=True),
            ContextSection("old_history", "很长的旧对话" * 20, priority=1),
        ),
        budget=ContextBudget(input_tokens=20, output_tokens=8),
    )

    assert result.kept_sections == ("identity", "current_case")
    assert result.dropped_sections == ("old_history",)
    assert "金额=899, status=pending" in result.text
    assert "旧对话" not in result.text


def test_required_context_cannot_be_silently_truncated() -> None:
    with pytest.raises(ContextBudgetExceeded):
        build_context(
            (ContextSection("security", "不可删除的安全约束" * 10, priority=100, required=True),),
            budget=ContextBudget(input_tokens=2, output_tokens=8),
        )
