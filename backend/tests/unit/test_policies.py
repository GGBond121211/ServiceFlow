from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest

from serviceflow.domain.models import IssueType, Order, OrderStatus, RequestedAction
from serviceflow.domain.policies import evaluate_policy
from serviceflow.domain.results import Decision

REFERENCE_DATE = date(2026, 8, 9)


def delivered_order(*, amount: str = "199.00", days_ago: int = 3) -> Order:
    delivered_date = REFERENCE_DATE - timedelta(days=days_ago)
    return Order(
        id="ORDER-001",
        user_id="USER-001",
        status=OrderStatus.DELIVERED,
        total_amount=Decimal(amount),
        placed_at=datetime(2026, 7, 1, tzinfo=UTC),
        delivered_at=datetime.combine(delivered_date, time(hour=10), tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("order", "action", "issue", "expected_policy", "expected_decision"),
    [
        (None, RequestedAction.QUERY, IssueType.NONE, "POL-INFO-01", Decision.ASK_FOR_INFO),
        (delivered_order(), None, IssueType.NONE, "POL-INFO-01", Decision.ASK_FOR_INFO),
        (
            delivered_order(),
            RequestedAction.QUERY,
            IssueType.NONE,
            "POL-QUERY-01",
            Decision.EXPLAIN_ONLY,
        ),
        (
            Order(
                id="ORDER-002",
                user_id="USER-001",
                status=OrderStatus.PAID,
                total_amount=Decimal("299.00"),
                placed_at=datetime(2026, 8, 8, tzinfo=UTC),
            ),
            RequestedAction.CANCEL,
            IssueType.NONE,
            "POL-CANCEL-01",
            Decision.CANCEL,
        ),
        (
            delivered_order(days_ago=7),
            RequestedAction.REFUND,
            IssueType.CHANGED_MIND,
            "POL-REFUND-01",
            Decision.DIRECT_REFUND,
        ),
        (
            delivered_order(amount="500.01", days_ago=7),
            RequestedAction.REFUND,
            IssueType.QUALITY,
            "POL-APPROVAL-01",
            Decision.APPROVAL_REQUIRED,
        ),
        (
            delivered_order(days_ago=30),
            RequestedAction.EXCHANGE,
            IssueType.QUALITY,
            "POL-EXCHANGE-01",
            Decision.CREATE_EXCHANGE_TICKET,
        ),
        (
            delivered_order(days_ago=8),
            RequestedAction.REFUND,
            IssueType.CHANGED_MIND,
            "POL-TICKET-01",
            Decision.CREATE_SUPPORT_TICKET,
        ),
        (
            delivered_order(days_ago=31),
            RequestedAction.EXCHANGE,
            IssueType.QUALITY,
            "POL-TICKET-01",
            Decision.CREATE_SUPPORT_TICKET,
        ),
    ],
)
def test_policy_cases(
    order: Order | None,
    action: RequestedAction | None,
    issue: IssueType | None,
    expected_policy: str,
    expected_decision: Decision,
) -> None:
    result = evaluate_policy(
        order=order,
        requested_action=action,
        issue_type=issue,
        reference_date=REFERENCE_DATE,
    )

    assert result.policy_id == expected_policy
    assert result.decision is expected_decision
    assert result.reason
