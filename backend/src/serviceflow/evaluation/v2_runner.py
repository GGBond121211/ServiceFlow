"""V2 案例的证据记录与确定性评分。"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from serviceflow.evaluation.case_v2 import EvalCaseV2, V2RewardType


class V2ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    arguments: dict[str, object] = Field(default_factory=dict)
    call_id: str | None = None
    ok: bool | None = None
    code: str | None = None


class V2Execution(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    intent: str | None = None
    policy_id: str | None = None
    tool_calls: tuple[V2ToolCall, ...] = ()
    state_transitions: tuple[str, ...] = ()
    final_state: dict[str, object] = Field(default_factory=dict)
    assistant_message: str = ""
    confirmation_requested: bool = False
    approval_requested: bool = False
    handoff_created: bool = False
    refused: bool = False
    side_effect_count: int = 0
    environment: dict[str, bool] = Field(default_factory=dict)
    trace: list[dict[str, object]] = Field(default_factory=list)
    model: str | None = None
    prompt_version: str | None = None
    route_version: str | None = None
    index_version: str | None = None
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float | None = None
    error: str | None = None


class V2CaseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    passed: bool
    intent_correct: bool | None
    policy_correct: bool | None
    final_state_correct: bool
    allowed_tools_correct: bool
    tool_selection_correct: bool | None
    state_transition_correct: bool | None
    confirmation_correct: bool
    approval_correct: bool
    handoff_correct: bool
    refusal_correct: bool
    side_effect_correct: bool
    environment_correct: bool | None
    communicate_correct: bool | None
    failure_layers: tuple[str, ...] = ()
    execution: V2Execution


class V2EvaluationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_cases: int
    passed_cases: int
    failed_case_ids: list[str]
    metrics: dict[str, float | None]
    denominators: dict[str, int]
    total_latency_ms: float
    total_input_tokens: int
    total_output_tokens: int
    total_estimated_cost: float | None


class V2EvaluationRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_at: str
    experiment_id: str
    dataset_version: str
    commit: str
    case_results: list[V2CaseResult]
    summary: V2EvaluationSummary


V2Executor = Callable[[EvalCaseV2], Awaitable[V2Execution]]


async def run_v2_evaluation(
    *,
    cases: Sequence[EvalCaseV2],
    executor: V2Executor,
    dataset_version: str,
    experiment_id: str,
    commit: str,
) -> V2EvaluationRun:
    results: list[V2CaseResult] = []
    for case in cases:
        started = perf_counter()
        try:
            execution = await executor(case)
        except Exception as error:
            execution = V2Execution(
                status="ERROR",
                latency_ms=(perf_counter() - started) * 1000,
                error=f"{type(error).__name__}: {error}",
            )
        else:
            if execution.latency_ms == 0:
                execution = execution.model_copy(
                    update={"latency_ms": (perf_counter() - started) * 1000}
                )
        results.append(score_v2_case(case, execution))
    return V2EvaluationRun(
        run_at=datetime.now(UTC).isoformat(),
        experiment_id=experiment_id,
        dataset_version=dataset_version,
        commit=commit,
        case_results=results,
        summary=calculate_v2_summary(results),
    )


def score_v2_case(case: EvalCaseV2, execution: V2Execution) -> V2CaseResult:
    expected = case.expected
    intent_correct = _match_optional(expected.intent, execution.intent)
    policy_correct = _match_optional(expected.policy_id, execution.policy_id)
    final_state_correct = _state_matches(
        expected.final_state.model_dump(mode="json"), execution.final_state
    )

    actual_tools = tuple(call.name for call in execution.tool_calls)
    allowed = set(expected.allowed_tools)
    allowed_tools_correct = set(actual_tools) <= allowed
    tool_selection_correct = None
    if expected.expected_tool_calls:
        expected_tools = tuple(_tool_signature(item) for item in expected.expected_tool_calls)
        actual_signatures = tuple(
            _tool_signature(call.model_dump(mode="json")) for call in execution.tool_calls
        )
        if V2RewardType.ACTION in case.reward_basis:
            tool_selection_correct = actual_signatures == expected_tools
        else:
            tool_selection_correct = Counter(actual_signatures) == Counter(expected_tools)

    state_transition_correct = None
    if expected.state_transitions:
        state_transition_correct = tuple(execution.state_transitions) == tuple(
            expected.state_transitions
        )

    confirmation_correct = execution.confirmation_requested == expected.requires_confirmation
    approval_correct = execution.approval_requested == expected.requires_approval
    handoff_correct = execution.handoff_created == expected.allow_handoff
    refusal_correct = execution.refused == expected.must_refuse
    side_effect_correct = True
    if expected.side_effect_must_not_occur or expected.must_refuse:
        side_effect_correct = execution.side_effect_count == 0

    environment_correct = None
    if expected.env_assertions:
        environment_correct = all(
            execution.environment.get(name, False) for name in expected.env_assertions
        )

    communicate_correct = None
    if expected.communicate_info:
        communicate_correct = all(
            phrase in execution.assistant_message for phrase in expected.communicate_info
        )

    checks: list[tuple[str, bool | None]] = [
        ("intent", intent_correct),
        ("policy", policy_correct),
        ("final_state", final_state_correct),
        ("allowed_tools", allowed_tools_correct),
        ("tool", tool_selection_correct),
        ("state_transition", state_transition_correct),
        ("confirmation", confirmation_correct),
        ("approval", approval_correct),
        ("handoff", handoff_correct),
        ("refusal", refusal_correct),
        ("side_effect", side_effect_correct),
        ("environment", environment_correct),
        ("communication", communicate_correct),
    ]
    failure_layers = tuple(name for name, result in checks if result is False)
    if execution.error:
        failure_layers = (*failure_layers, "execution")
    return V2CaseResult(
        case_id=case.id,
        passed=not failure_layers and execution.error is None,
        intent_correct=intent_correct,
        policy_correct=policy_correct,
        final_state_correct=final_state_correct,
        allowed_tools_correct=allowed_tools_correct,
        tool_selection_correct=tool_selection_correct,
        state_transition_correct=state_transition_correct,
        confirmation_correct=confirmation_correct,
        approval_correct=approval_correct,
        handoff_correct=handoff_correct,
        refusal_correct=refusal_correct,
        side_effect_correct=side_effect_correct,
        environment_correct=environment_correct,
        communicate_correct=communicate_correct,
        failure_layers=failure_layers,
        execution=execution,
    )


def calculate_v2_summary(results: Sequence[V2CaseResult]) -> V2EvaluationSummary:
    total = len(results)
    passed = sum(result.passed for result in results)
    failed = [result.case_id for result in results if not result.passed]
    metrics: dict[str, float | None] = {
        "case_pass_rate": _ratio(passed, total),
        "intent_accuracy": _optional_ratio(results, "intent_correct"),
        "policy_accuracy": _optional_ratio(results, "policy_correct"),
        "final_state_accuracy": _ratio(
            sum(result.final_state_correct for result in results), total
        ),
        "allowed_tools_accuracy": _ratio(
            sum(result.allowed_tools_correct for result in results), total
        ),
        "tool_selection_accuracy": _optional_ratio(results, "tool_selection_correct"),
        "state_transition_accuracy": _optional_ratio(results, "state_transition_correct"),
        "confirmation_gate_accuracy": _ratio(
            sum(result.confirmation_correct for result in results), total
        ),
        "approval_gate_accuracy": _ratio(sum(result.approval_correct for result in results), total),
        "handoff_accuracy": _ratio(sum(result.handoff_correct for result in results), total),
        "refusal_accuracy": _ratio(sum(result.refusal_correct for result in results), total),
        "no_side_effect_accuracy": _ratio(
            sum(result.side_effect_correct for result in results), total
        ),
        "environment_assertion_accuracy": _optional_ratio(results, "environment_correct"),
        "communication_accuracy": _optional_ratio(results, "communicate_correct"),
        "error_rate": _ratio(sum(result.execution.error is not None for result in results), total),
    }
    denominators = {
        "intent_accuracy": sum(result.intent_correct is not None for result in results),
        "policy_accuracy": sum(result.policy_correct is not None for result in results),
        "tool_selection_accuracy": sum(
            result.tool_selection_correct is not None for result in results
        ),
        "state_transition_accuracy": sum(
            result.state_transition_correct is not None for result in results
        ),
        "environment_assertion_accuracy": sum(
            result.environment_correct is not None for result in results
        ),
        "communication_accuracy": sum(
            result.communicate_correct is not None for result in results
        ),
    }
    costs = [result.execution.estimated_cost for result in results]
    total_cost = None if any(cost is None for cost in costs) else sum(costs, 0.0)
    return V2EvaluationSummary(
        total_cases=total,
        passed_cases=passed,
        failed_case_ids=failed,
        metrics=metrics,
        denominators=denominators,
        total_latency_ms=sum(result.execution.latency_ms for result in results),
        total_input_tokens=sum(result.execution.input_tokens for result in results),
        total_output_tokens=sum(result.execution.output_tokens for result in results),
        total_estimated_cost=total_cost,
    )


def write_v2_results(results: Sequence[V2CaseResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for result in results:
        payload = result.model_dump(mode="json")
        execution = payload.pop("execution")
        payload = {"case_id": result.case_id, "execution": execution, "score": payload}
        lines.append(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _match_optional(expected: str | None, actual: str | None) -> bool | None:
    if expected is None:
        return None
    return expected == actual


def _state_matches(expected: dict[str, object], actual: dict[str, object]) -> bool:
    return all(_value(actual.get(key)) == _value(value) for key, value in expected.items())


def _tool_signature(value: dict[str, object]) -> str:
    name = value.get("name", value.get("tool", ""))
    arguments = value.get("arguments", {})
    if not isinstance(arguments, dict):
        arguments = {}
    return json.dumps(
        {"name": str(name), "arguments": arguments},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _value(value: object) -> object:
    enum_value = getattr(value, "value", None)
    return enum_value if enum_value is not None else value


def _optional_ratio(results: Sequence[V2CaseResult], field: str) -> float | None:
    values = [getattr(result, field) for result in results]
    evaluated = [value for value in values if value is not None]
    if not evaluated:
        return None
    return sum(evaluated) / len(evaluated)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0
