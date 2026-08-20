from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from time import perf_counter

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from serviceflow.agent.graph import build_service_graph
from serviceflow.agent.intent import PROMPT_VERSION
from serviceflow.agent.model import StructuredModel
from serviceflow.domain.models import Order
from serviceflow.evaluation.models import EvalCase, EvalCategory
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.tables import ApprovalRow, RefundRow, TicketRow, UserRow

REFERENCE_DATE = date(2026, 8, 1)
CORE_CATEGORY_VALUES = {
    EvalCategory.NORMAL_HANDLING.value,
    EvalCategory.BUSINESS_BOUNDARY.value,
    EvalCategory.CLARIFICATION.value,
    EvalCategory.NATURAL_LANGUAGE_VARIANT.value,
}
COMPLEX_CATEGORY_VALUES = {
    EvalCategory.BLENDED_INTENT.value,
    EvalCategory.IMPLICIT_INTENT.value,
    EvalCategory.NOISY_CONTEXT.value,
    EvalCategory.CORRECTION_NEGATION.value,
    EvalCategory.MULTI_TURN_STATE.value,
    EvalCategory.AMBIGUOUS_REQUEST.value,
}


class CaseEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    expected_decision: str
    actual_decision: str | None
    expected_policy_id: str
    actual_policy_id: str | None
    expected_tools: list[str]
    actual_tools: list[str]
    expected_final_state: dict[str, str]
    actual_final_state: dict[str, str]
    outcome_correct: bool
    final_state_correct: bool
    policy_correct: bool
    tools_correct: bool
    clarification_correct: bool | None
    latency_ms: float
    input_tokens: int
    output_tokens: int
    model: str | None
    prompt_version: str | None
    error: str | None
    category: str | None = None
    expected_intent: str | None = None
    actual_intent: str | None = None
    expected_issue_type: str | None = None
    actual_issue_type: str | None = None


class EvaluationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_cases: int
    completed_cases: int
    outcome_accuracy: float
    final_state_accuracy: float
    policy_accuracy: float
    tool_accuracy: float
    clarification_completion_rate: float
    total_latency_ms: float
    average_latency_ms: float
    total_input_tokens: int
    total_output_tokens: int
    failed_case_ids: list[str]


class EvaluationRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_at: str
    commit: str
    models: list[str]
    prompt_versions: list[str]
    summary: EvaluationSummary
    group_summaries: dict[str, EvaluationSummary] = Field(default_factory=dict)
    cases: list[CaseEvaluation]


async def run_evaluation(
    *,
    cases: Sequence[EvalCase],
    model: StructuredModel,
    session_factory: async_sessionmaker[AsyncSession],
    commit: str,
) -> EvaluationRun:
    results = []
    for case in cases:
        results.append(await _run_case(case=case, model=model, session_factory=session_factory))

    models = set()
    for result in results:
        if result.model:
            models.add(result.model)

    prompt_versions = set()
    for result in results:
        if result.prompt_version:
            prompt_versions.add(result.prompt_version)

    return EvaluationRun(
        run_at=datetime.now(UTC).isoformat(),
        commit=commit,
        models=sorted(models),
        prompt_versions=sorted(prompt_versions),
        summary=calculate_summary(results),
        group_summaries=calculate_group_summaries(results),
        cases=results,
    )


def calculate_summary(cases: Sequence[CaseEvaluation]) -> EvaluationSummary:
    total = len(cases)
    clarification = []
    total_latency = 0.0
    failed = []
    completed_cases = 0
    outcome_correct = 0
    final_state_correct = 0
    policy_correct = 0
    tools_correct = 0
    total_input_tokens = 0
    total_output_tokens = 0
    for case in cases:
        if case.clarification_correct is not None:
            clarification.append(case.clarification_correct)
        total_latency += case.latency_ms
        if not case.error:
            completed_cases += 1
        if case.outcome_correct:
            outcome_correct += 1
        if case.final_state_correct:
            final_state_correct += 1
        if case.policy_correct:
            policy_correct += 1
        if case.tools_correct:
            tools_correct += 1
        total_input_tokens += case.input_tokens
        total_output_tokens += case.output_tokens
        if not _case_passed(case):
            failed.append(case.case_id)
    return EvaluationSummary(
        total_cases=total,
        completed_cases=completed_cases,
        outcome_accuracy=_ratio(outcome_correct, total),
        final_state_accuracy=_ratio(final_state_correct, total),
        policy_accuracy=_ratio(policy_correct, total),
        tool_accuracy=_ratio(tools_correct, total),
        clarification_completion_rate=_ratio(sum(clarification), len(clarification)),
        total_latency_ms=total_latency,
        average_latency_ms=_ratio(total_latency, total),
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        failed_case_ids=failed,
    )


def calculate_group_summaries(
    cases: Sequence[CaseEvaluation],
) -> dict[str, EvaluationSummary]:
    core = []
    complex_cases = []
    for case in cases:
        if case.category in CORE_CATEGORY_VALUES:
            core.append(case)
        if case.category in COMPLEX_CATEGORY_VALUES:
            complex_cases.append(case)
    groups: dict[str, EvaluationSummary] = {}
    if core:
        groups["core_40"] = calculate_summary(core)
    if complex_cases:
        groups["complex_60"] = calculate_summary(complex_cases)
    return groups


async def _run_case(
    *,
    case: EvalCase,
    model: StructuredModel,
    session_factory: async_sessionmaker[AsyncSession],
) -> CaseEvaluation:
    started = perf_counter()
    states: list[dict[str, object]] = []
    error: str | None = None
    try:
        await _reset_case_database(case, session_factory)
        graph = build_service_graph(
            model=model,
            session_factory=session_factory,
            checkpointer=InMemorySaver(),
        )
        config = {"configurable": {"thread_id": case.id}}
        for message in case.messages:
            state = await graph.ainvoke(
                {
                    "thread_id": case.id,
                    "user_id": case.user_id,
                    "user_message": message,
                    "reference_date": REFERENCE_DATE.isoformat(),
                },
                config=config,
            )
            states.append(dict(state))

        approval_decision = _approval_decision(case)
        if approval_decision is not None and _approval_is_pending(states[-1]):
            state = await graph.ainvoke(
                Command(resume={"approved": approval_decision}),
                config=config,
            )
            states.append(dict(state))
    except Exception as exc:  # 模型失败的案例也必须出现在评测报告中。
        error = f"{type(exc).__name__}: {exc}"

    final = {}
    if states:
        final = states[-1]
    actual_final_state = await _read_final_state(case, session_factory)
    expected_final_state = case.expected.final_state.model_dump(mode="json", exclude_none=True)
    actual_decision = _text(final.get("decision"))
    actual_policy = _text(final.get("policy_id"))
    actual_tools = []
    for event in final.get("tool_events", []):
        if isinstance(event, dict) and "tool" in event:
            actual_tools.append(str(event["tool"]))
    expected_decision = case.expected.decision.value
    final_state_correct = actual_final_state == expected_final_state
    decision_correct = actual_decision == expected_decision
    outcome_correct = decision_correct and final_state_correct and error is None
    clarification_correct = _clarification_score(
        case=case,
        states=states,
        outcome_correct=outcome_correct,
    )
    token_usage = final.get("token_usage", {})
    if not isinstance(token_usage, dict):
        token_usage = {}
    expected_intent = None
    if case.expected.intent is not None:
        expected_intent = case.expected.intent.value
    expected_issue_type = None
    if case.expected.issue_type is not None:
        expected_issue_type = case.expected.issue_type.value
    prompt_version = _text(final.get("prompt_version"))
    if prompt_version is None:
        prompt_version = PROMPT_VERSION
    return CaseEvaluation(
        case_id=case.id,
        category=case.category.value,
        expected_decision=expected_decision,
        actual_decision=actual_decision,
        expected_policy_id=case.expected.policy_id,
        actual_policy_id=actual_policy,
        expected_tools=list(case.expected.expected_tools),
        actual_tools=actual_tools,
        expected_final_state=expected_final_state,
        actual_final_state=actual_final_state,
        outcome_correct=outcome_correct,
        final_state_correct=final_state_correct,
        policy_correct=actual_policy == case.expected.policy_id,
        tools_correct=actual_tools == list(case.expected.expected_tools),
        clarification_correct=clarification_correct,
        latency_ms=(perf_counter() - started) * 1000,
        input_tokens=int(token_usage.get("input", 0)),
        output_tokens=int(token_usage.get("output", 0)),
        model=_text(final.get("model_name")),
        prompt_version=prompt_version,
        error=error,
        expected_intent=expected_intent,
        actual_intent=_text(final.get("requested_action")),
        expected_issue_type=expected_issue_type,
        actual_issue_type=_text(final.get("issue_type")),
    )


async def _reset_case_database(
    case: EvalCase,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await session.run_sync(
            lambda sync_session: Base.metadata.drop_all(sync_session.get_bind())
        )
        await session.run_sync(
            lambda sync_session: Base.metadata.create_all(sync_session.get_bind())
        )
        session.add(UserRow(id=case.user_id, display_name="评测用户"))
        state = case.initial_state
        if state.order_id is not None:
            if state.status is None or state.total_amount is None:
                raise ValueError(f"{case.id}: order state is incomplete")
            delivered_at = None
            if state.delivered_days_ago is not None:
                delivered_date = REFERENCE_DATE - timedelta(days=state.delivered_days_ago)
                delivered_at = datetime.combine(delivered_date, time(hour=10), tzinfo=UTC)
            await OrderRepository(session).add(
                Order(
                    id=state.order_id,
                    user_id=case.user_id,
                    status=state.status,
                    total_amount=state.total_amount,
                    placed_at=datetime(2026, 7, 1, tzinfo=UTC),
                    delivered_at=delivered_at,
                )
            )
        await session.commit()


async def _read_final_state(
    case: EvalCase,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, str]:
    order_id = case.initial_state.order_id
    if order_id is None:
        return {}
    final: dict[str, str] = {}
    async with session_factory() as session:
        order = await OrderRepository(session).get(order_id)
        if order is not None:
            final["order_status"] = order.status.value
        refund = await session.scalar(
            select(RefundRow)
            .where(RefundRow.order_id == order_id)
            .order_by(RefundRow.created_at.desc())
            .limit(1)
        )
        ticket = await session.scalar(
            select(TicketRow)
            .where(TicketRow.order_id == order_id)
            .order_by(TicketRow.created_at.desc())
            .limit(1)
        )
        approval = await session.scalar(
            select(ApprovalRow)
            .where(ApprovalRow.order_id == order_id)
            .order_by(ApprovalRow.created_at.desc())
            .limit(1)
        )
    if refund is not None:
        final["refund_status"] = refund.status
    if approval is not None:
        final["approval_status"] = approval.status
    if ticket is not None:
        final["ticket_status"] = ticket.status
    return final


def _approval_decision(case: EvalCase) -> bool | None:
    if case.approval_decision is not None:
        return case.approval_decision
    expected = case.expected.final_state.approval_status
    if expected is None or expected.value == "pending":
        return None
    if expected.value == "approved":
        return True
    return False


def _approval_is_pending(state: dict[str, object]) -> bool:
    final = state.get("final_business_state", {})
    return isinstance(final, dict) and final.get("approval_status") == "pending"


def _clarification_score(
    *,
    case: EvalCase,
    states: Sequence[dict[str, object]],
    outcome_correct: bool,
) -> bool | None:
    is_clarification = (
        case.category is EvalCategory.CLARIFICATION
        or len(case.messages) > 1
        or case.expected.decision.value == "ask_for_info"
    )
    if not is_clarification:
        return None
    asked_first = bool(states) and _text(states[0].get("decision")) == "ask_for_info"
    if len(case.messages) == 1:
        return asked_first and outcome_correct
    return asked_first and outcome_correct


def _case_passed(case: CaseEvaluation) -> bool:
    return (
        case.outcome_correct
        and case.final_state_correct
        and case.policy_correct
        and case.tools_correct
        and case.clarification_correct is not False
        and case.error is None
    )


def _ratio(numerator: float | int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
