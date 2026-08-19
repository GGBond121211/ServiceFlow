import json
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from serviceflow.domain.models import Order
from serviceflow.domain.policies import evaluate_policy
from serviceflow.evaluation.loader import DEFAULT_EVAL_PATH, load_eval_cases
from serviceflow.evaluation.models import EvalCategory

REFERENCE_DATE = date(2026, 8, 1)
SEED_PATH = Path(__file__).parents[1] / "fixtures" / "seed_data.json"
COMPLEX_EVAL_PATH = (
    Path(__file__).parents[3] / "tests" / "eval_cases" / "serviceflow_v1_complex_60.jsonl"
)


def test_loader_reads_forty_unique_cases_in_required_categories() -> None:
    cases = load_eval_cases(DEFAULT_EVAL_PATH)

    assert len(cases) == 40
    case_ids = set()
    for case in cases:
        case_ids.add(case.id)
    assert len(case_ids) == 40
    assert Counter(case.category for case in cases) == {
        EvalCategory.NORMAL_HANDLING: 16,
        EvalCategory.BUSINESS_BOUNDARY: 10,
        EvalCategory.CLARIFICATION: 6,
        EvalCategory.NATURAL_LANGUAGE_VARIANT: 8,
    }


def test_loader_combines_core_and_complex_partitions_into_one_hundred_cases() -> None:
    cases = load_eval_cases([DEFAULT_EVAL_PATH, COMPLEX_EVAL_PATH])

    assert len(cases) == 100
    case_ids = set()
    for case in cases:
        case_ids.add(case.id)
    assert len(case_ids) == 100


def test_eval_order_ids_exist_in_seed_fixture() -> None:
    seed_data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    seed_order_ids = set()
    for order in seed_data["orders"]:
        seed_order_ids.add(order["id"])

    for case in load_eval_cases(DEFAULT_EVAL_PATH):
        if case.initial_state.order_id is not None:
            assert case.initial_state.order_id in seed_order_ids


def test_policy_expectations_recompute_from_initial_state() -> None:
    for case in load_eval_cases(DEFAULT_EVAL_PATH):
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
