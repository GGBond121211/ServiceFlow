from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from serviceflow.domain.models import (
    Approval,
    ApprovalStatus,
    IssueType,
    Order,
    OrderItem,
    OrderStatus,
    Refund,
    RefundStatus,
    RequestedAction,
    Ticket,
    TicketKind,
    TicketStatus,
)
from serviceflow.domain.results import Decision, PolicyDecision


def test_domain_enum_values_are_stable() -> None:
    assert OrderStatus.PAID == "paid"
    assert RequestedAction.REFUND == "refund"
    assert IssueType.QUALITY == "quality"
    assert Decision.APPROVAL_REQUIRED == "approval_required"


def test_order_uses_decimal_amount_and_is_frozen() -> None:
    order = Order(
        id="ORDER-001",
        user_id="USER-001",
        status=OrderStatus.PAID,
        total_amount=Decimal("199.00"),
        placed_at=datetime(2026, 7, 1, tzinfo=UTC),
    )

    assert isinstance(order.total_amount, Decimal)
    with pytest.raises(FrozenInstanceError):
        order.status = OrderStatus.CANCELLED  # type: ignore[misc]


def test_related_domain_objects_keep_structured_business_data() -> None:
    created_at = datetime(2026, 7, 2, tzinfo=UTC)
    item = OrderItem(
        id="ITEM-001",
        order_id="ORDER-001",
        product_name="Mechanical Keyboard",
        category="electronics",
        unit_price=Decimal("199.00"),
        quantity=1,
    )
    refund = Refund(
        id="REFUND-001",
        order_id="ORDER-001",
        amount=Decimal("199.00"),
        status=RefundStatus.COMPLETED,
        created_at=created_at,
    )
    ticket = Ticket(
        id="TICKET-001",
        order_id="ORDER-001",
        kind=TicketKind.EXCHANGE,
        status=TicketStatus.OPEN,
        summary="Keyboard key does not work",
        created_at=created_at,
    )
    approval = Approval(
        id="APPROVAL-001",
        order_id="ORDER-001",
        requested_action=RequestedAction.REFUND,
        status=ApprovalStatus.PENDING,
        created_at=created_at,
    )

    assert item.unit_price == Decimal("199.00")
    assert refund.status is RefundStatus.COMPLETED
    assert ticket.kind is TicketKind.EXCHANGE
    assert approval.status is ApprovalStatus.PENDING


def test_policy_decision_records_policy_result() -> None:
    result = PolicyDecision(
        policy_id="POL-REFUND-01",
        decision=Decision.DIRECT_REFUND,
        reason="七天内送达订单",
    )

    assert result.policy_id == "POL-REFUND-01"
    assert result.decision is Decision.DIRECT_REFUND
    assert result.reason == "七天内送达订单"
