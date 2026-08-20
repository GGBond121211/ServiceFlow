import json
from pathlib import Path

from serviceflow.evaluation.report import write_evaluation_outputs
from serviceflow.evaluation.runner import (
    CaseEvaluation,
    EvaluationRun,
    calculate_group_summaries,
    calculate_summary,
)


def test_metrics_use_deterministic_case_scores_and_list_failures(tmp_path: Path) -> None:
    cases = [
        _result("case-pass", True, True, True, True, True),
        _result("case-tool-fail", False, True, True, False, False),
        _result("case-state-fail", False, False, False, True, None),
    ]
    summary = calculate_summary(cases)
    run = EvaluationRun(
        run_at="2026-08-09T00:00:00+00:00",
        commit="test-commit",
        models=["fake-model"],
        prompt_versions=["service_agent_v1"],
        summary=summary,
        cases=cases,
    )

    json_path, markdown_path = write_evaluation_outputs(run, tmp_path)
    saved = json.loads(json_path.read_text(encoding="utf-8"))
    report = markdown_path.read_text(encoding="utf-8")

    assert summary.total_cases == 3
    assert summary.completed_cases == 3
    assert summary.outcome_accuracy == 1 / 3
    assert summary.final_state_accuracy == 2 / 3
    assert summary.policy_accuracy == 2 / 3
    assert summary.tool_accuracy == 2 / 3
    assert summary.clarification_completion_rate == 0.5
    assert summary.failed_case_ids == ["case-tool-fail", "case-state-fail"]
    assert saved["summary"]["failed_case_ids"] == summary.failed_case_ids
    assert "case-tool-fail" in report
    assert "case-state-fail" in report
    assert "33.33%" in report
    assert "期望结果：" in report
    assert "实际结果：" in report


def test_report_separates_core_complex_and_overall_metrics(tmp_path: Path) -> None:
    cases = [
        _result("core-pass", True, True, True, True, None, "normal_handling"),
        _result("core-fail", False, False, False, False, None, "business_boundary"),
        _result("complex-pass", True, True, True, True, None, "blended_intent"),
        _result("complex-pass-2", True, True, True, True, None, "multi_turn_state"),
    ]
    run = EvaluationRun(
        run_at="2026-08-11T00:00:00+00:00",
        commit="test-commit",
        models=["fake-model"],
        prompt_versions=["service_agent_v1"],
        summary=calculate_summary(cases),
        group_summaries=calculate_group_summaries(cases),
        cases=cases,
    )

    json_path, markdown_path = write_evaluation_outputs(
        run,
        tmp_path,
        stem="serviceflow-v1-100",
    )
    saved = json.loads(json_path.read_text(encoding="utf-8"))
    report = markdown_path.read_text(encoding="utf-8")

    assert json_path.name == "serviceflow-v1-100-results.json"
    assert saved["group_summaries"]["core_40"]["total_cases"] == 2
    assert saved["group_summaries"]["complex_60"]["total_cases"] == 2
    assert "核心40案" in report
    assert "复杂中文60案" in report
    assert "50.00%" in report
    assert "100.00%" in report


def _result(
    case_id: str,
    outcome: bool,
    final_state: bool,
    policy: bool,
    tools: bool,
    clarification: bool | None,
    category: str | None = None,
) -> CaseEvaluation:
    actual_decision = "create_support_ticket"
    if outcome:
        actual_decision = "cancel"

    actual_policy_id = "POL-TICKET-01"
    if policy:
        actual_policy_id = "POL-CANCEL-01"

    actual_tools = ["get_order"]
    if tools:
        actual_tools = ["get_order", "cancel_order"]

    actual_final_state = {"order_status": "paid"}
    if final_state:
        actual_final_state = {"order_status": "cancelled"}

    return CaseEvaluation(
        case_id=case_id,
        expected_decision="cancel",
        actual_decision=actual_decision,
        expected_policy_id="POL-CANCEL-01",
        actual_policy_id=actual_policy_id,
        expected_tools=["get_order", "cancel_order"],
        actual_tools=actual_tools,
        expected_final_state={"order_status": "cancelled"},
        actual_final_state=actual_final_state,
        outcome_correct=outcome,
        final_state_correct=final_state,
        policy_correct=policy,
        tools_correct=tools,
        clarification_correct=clarification,
        latency_ms=12.5,
        input_tokens=10,
        output_tokens=5,
        model="fake-model",
        prompt_version="service_agent_v1",
        error=None,
        category=category,
    )
