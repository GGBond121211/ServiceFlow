from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from serviceflow.domain.models import Order
from serviceflow.domain.policies import evaluate_policy
from serviceflow.evaluation.loader import load_eval_cases
from serviceflow.evaluation.models import EvalCategory

COMPLEX_EVAL_PATH = (
    Path(__file__).parents[3] / "tests" / "eval_cases" / "serviceflow_v1_complex_60.jsonl"
)
REFERENCE_DATE = date(2026, 8, 1)


def test_complex_suite_has_sixty_unique_cases_across_realistic_categories() -> None:
    cases = load_eval_cases(COMPLEX_EVAL_PATH)

    assert len(cases) == 60
    case_ids = set()
    for case in cases:
        case_ids.add(case.id)
    assert len(case_ids) == 60
    assert Counter(case.category for case in cases) == {
        EvalCategory.BLENDED_INTENT: 12,
        EvalCategory.IMPLICIT_INTENT: 10,
        EvalCategory.NOISY_CONTEXT: 10,
        EvalCategory.CORRECTION_NEGATION: 10,
        EvalCategory.MULTI_TURN_STATE: 12,
        EvalCategory.AMBIGUOUS_REQUEST: 6,
    }


def test_complex_suite_is_materially_harder_than_short_single_intent_prompts() -> None:
    cases = load_eval_cases(COMPLEX_EVAL_PATH)
    messages = []
    for case in cases:
        for message in case.messages:
            messages.append(message)

    long_message_count = 0
    for message in messages:
        if len(message) >= 45:
            long_message_count += 1
    assert long_message_count >= 24

    multi_message_case_count = 0
    for case in cases:
        if len(case.messages) >= 2:
            multi_message_case_count += 1
    assert multi_message_case_count >= 12

    missing_intent_count = 0
    for case in cases:
        if case.expected.intent is None:
            missing_intent_count += 1
    assert missing_intent_count == 6

    for message in messages:
        contains_chinese = False
        for character in message:
            if "\u4e00" <= character <= "\u9fff":
                contains_chinese = True
                break
        assert contains_chinese


def test_ambiguous_cases_ask_for_clarification_without_using_tools() -> None:
    cases = load_eval_cases(COMPLEX_EVAL_PATH)
    ambiguous = []
    for case in cases:
        if case.category is EvalCategory.AMBIGUOUS_REQUEST:
            ambiguous.append(case)

    for case in ambiguous:
        assert case.expected.intent is None
        assert case.expected.policy_id == "POL-INFO-01"
        assert case.expected.decision.value == "ask_for_info"
        assert case.expected.expected_tools == ()


def test_complex_suite_policy_expectations_match_the_domain_rules() -> None:
    for case in load_eval_cases(COMPLEX_EVAL_PATH):
        state = case.initial_state
        order = None
        if state.order_id is not None:
            assert state.status is not None
            assert state.total_amount is not None
            delivered_at = None
            if state.delivered_days_ago is not None:
                delivered_date = REFERENCE_DATE - timedelta(days=state.delivered_days_ago)
                delivered_at = datetime.combine(delivered_date, time(hour=10), tzinfo=UTC)
            order = Order(
                id=state.order_id,
                user_id=case.user_id,
                status=state.status,
                total_amount=Decimal(state.total_amount),
                placed_at=datetime(2026, 7, 1, tzinfo=UTC),
                delivered_at=delivered_at,
            )

        result = evaluate_policy(
            order=order,
            requested_action=case.expected.intent,
            issue_type=case.expected.issue_type,
            reference_date=REFERENCE_DATE,
        )

        assert result.policy_id == case.expected.policy_id, case.id
        assert result.decision is case.expected.decision, case.id
