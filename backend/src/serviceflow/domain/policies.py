from datetime import date
from decimal import Decimal

from serviceflow.domain.models import IssueType, Order, OrderStatus, RequestedAction
from serviceflow.domain.results import Decision, PolicyDecision

APPROVAL_AMOUNT_THRESHOLD = Decimal("500.00")
REFUND_WINDOW_DAYS = 7
EXCHANGE_WINDOW_DAYS = 30


def evaluate_policy(
    *,
    order: Order | None,
    requested_action: RequestedAction | None,
    issue_type: IssueType | None,
    reference_date: date,
) -> PolicyDecision:
    if order is None or requested_action is None:
        return PolicyDecision(
            policy_id="POL-INFO-01",
            decision=Decision.ASK_FOR_INFO,
            reason="需要提供订单号和处理事项",
        )

    if requested_action is RequestedAction.QUERY:
        return PolicyDecision(
            policy_id="POL-QUERY-01",
            decision=Decision.EXPLAIN_ONLY,
            reason="用户只是在查询订单信息",
        )

    if requested_action is RequestedAction.CANCEL and order.status is OrderStatus.PAID:
        return PolicyDecision(
            policy_id="POL-CANCEL-01",
            decision=Decision.CANCEL,
            reason="已付款且未发货的订单可以取消",
        )

    days_since_delivery = _days_since_delivery(order=order, reference_date=reference_date)

    if (
        requested_action is RequestedAction.REFUND
        and order.status is OrderStatus.DELIVERED
        and days_since_delivery is not None
        and 0 <= days_since_delivery <= REFUND_WINDOW_DAYS
    ):
        if order.total_amount > APPROVAL_AMOUNT_THRESHOLD:
            return PolicyDecision(
                policy_id="POL-APPROVAL-01",
                decision=Decision.APPROVAL_REQUIRED,
                reason="超过 500 元的退款需要人工审批",
            )
        return PolicyDecision(
            policy_id="POL-REFUND-01",
            decision=Decision.DIRECT_REFUND,
            reason="已送达订单仍在七天退款期限内",
        )

    if (
        requested_action is RequestedAction.EXCHANGE
        and issue_type is IssueType.QUALITY
        and order.status is OrderStatus.DELIVERED
        and days_since_delivery is not None
        and 0 <= days_since_delivery <= EXCHANGE_WINDOW_DAYS
    ):
        return PolicyDecision(
            policy_id="POL-EXCHANGE-01",
            decision=Decision.CREATE_EXCHANGE_TICKET,
            reason="商品质量问题仍在三十天换货期限内",
        )

    return PolicyDecision(
        policy_id="POL-TICKET-01",
        decision=Decision.CREATE_SUPPORT_TICKET,
        reason="这条请求需要人工客服处理",
    )


def _days_since_delivery(*, order: Order, reference_date: date) -> int | None:
    if order.delivered_at is None:
        return None
    return (reference_date - order.delivered_at.date()).days
