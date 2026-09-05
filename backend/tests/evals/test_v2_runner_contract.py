import json
from pathlib import Path

import pytest

from serviceflow.evaluation.case_v2 import EvalCaseV2
from serviceflow.evaluation.v2_runner import (
    V2Execution,
    run_v2_evaluation,
    score_v2_case,
    write_v2_results,
)


def _case(*, case_id: str = "v2-test-001", with_assertions: bool = True) -> EvalCaseV2:
    expected_tools = []
    transitions = []
    if with_assertions:
        expected_tools = [{"name": "get_order", "arguments": {"order_id": "ORDER-1"}}]
        transitions = ["CASE_OPEN", "COMPLETED"]
    return EvalCaseV2.model_validate(
        {
            "id": case_id,
            "category": "order_query",
            "split": "golden",
            "risk_level": "low",
            "origin": "handcrafted",
            "identity": {"tenant_id": "TENANT-A", "user_id": "USER-1"},
            "initial_state": {
                "order_id": "ORDER-1",
                "owner_user_id": "USER-1",
                "status": "paid",
                "total_amount": "99.00",
            },
            "user_scenario": {
                "reason_for_call": "查询订单状态",
                "known_info": {"order_id": "ORDER-1"},
            },
            "expected": {
                "intent": "query",
                "policy_id": "POL-QUERY-01",
                "allowed_tools": ["get_order"],
                "expected_tool_calls": expected_tools,
                "state_transitions": transitions,
                "final_state": {
                    "order_status": "paid",
                    "case_status": None,
                    "operation_status": None,
                    "refund_status": None,
                    "approval_status": None,
                    "ticket_status": None,
                },
            },
            "scoring": ["final_state", "tool_selection"],
        }
    )


def _execution(**updates: object) -> V2Execution:
    values: dict[str, object] = {
        "status": "COMPLETED",
        "intent": "query",
        "policy_id": "POL-QUERY-01",
        "tool_calls": [{"name": "get_order", "arguments": {"order_id": "ORDER-1"}}],
        "state_transitions": ["CASE_OPEN", "COMPLETED"],
        "final_state": {"order_status": "paid"},
        "environment": {"audit_written": True},
        "assistant_message": "订单状态为 paid",
        "model": "fake-v2-model",
        "input_tokens": 12,
        "output_tokens": 6,
    }
    values.update(updates)
    return V2Execution.model_validate(values)


def test_score_v2_case_checks_tool_arguments_and_state_transitions() -> None:
    case = _case()

    passed = score_v2_case(case, _execution())
    assert passed.passed is True
    assert passed.tool_selection_correct is True
    assert passed.state_transition_correct is True
    assert passed.failure_layers == ()

    failed = score_v2_case(
        case,
        _execution(
            tool_calls=[{"name": "get_order", "arguments": {"order_id": "ORDER-2"}}],
            state_transitions=["CASE_OPEN", "PROCESSING", "COMPLETED"],
        ),
    )
    assert failed.passed is False
    assert failed.tool_selection_correct is False
    assert failed.state_transition_correct is False
    assert "tool" in failed.failure_layers
    assert "state_transition" in failed.failure_layers


@pytest.mark.asyncio
async def test_run_v2_evaluation_keeps_errors_and_marks_missing_metrics_not_evaluable() -> None:
    cases = [
        _case(with_assertions=False),
        _case(case_id="v2-test-002", with_assertions=False),
    ]

    async def execute(case: EvalCaseV2) -> V2Execution:
        if case.id == "v2-test-002":
            raise RuntimeError("provider unavailable")
        return _execution(tool_calls=[], state_transitions=[])

    run = await run_v2_evaluation(
        cases=cases,
        executor=execute,
        dataset_version="v2-test",
        experiment_id="e0-test",
        commit="test-commit",
    )

    assert run.summary.total_cases == 2
    assert run.summary.failed_case_ids == ["v2-test-002"]
    assert run.summary.metrics["tool_selection_accuracy"] is None
    assert run.case_results[1].execution.error == "RuntimeError: provider unavailable"


def test_write_v2_results_preserves_raw_execution_and_score(tmp_path: Path) -> None:
    case = _case()
    result = score_v2_case(case, _execution())
    output = tmp_path / "raw.jsonl"

    write_v2_results([result], output)

    line = output.read_text(encoding="utf-8").splitlines()[0]
    saved = json.loads(line)
    assert saved["case_id"] == "v2-test-001"
    assert saved["execution"]["tool_calls"]
    assert saved["score"]["passed"] is True
