from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class OrderStatus(StrEnum):
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUND_PENDING = "refund_pending"
    REFUNDED = "refunded"
    TICKET_OPEN = "ticket_open"


class RequestedAction(StrEnum):
    QUERY = "query"
    CANCEL = "cancel"
    REFUND = "refund"
    EXCHANGE = "exchange"
    REPAIR = "repair"


class IssueType(StrEnum):
    NONE = "none"
    QUALITY = "quality"
    CHANGED_MIND = "changed_mind"
    OTHER = "other"


class RefundStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"


class TicketKind(StrEnum):
    EXCHANGE = "exchange"
    REPAIR = "repair"
    SUPPORT = "support"


class TicketStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class OrderItem:
    id: str
    order_id: str
    product_name: str
    category: str
    unit_price: Decimal
    quantity: int


@dataclass(frozen=True, slots=True)
class Order:
    id: str
    user_id: str
    status: OrderStatus
    total_amount: Decimal
    placed_at: datetime
    delivered_at: datetime | None = None
    items: tuple[OrderItem, ...] = ()


@dataclass(frozen=True, slots=True)
class Refund:
    id: str
    order_id: str
    amount: Decimal
    status: RefundStatus
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Ticket:
    id: str
    order_id: str
    kind: TicketKind
    status: TicketStatus
    summary: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Approval:
    id: str
    order_id: str
    requested_action: RequestedAction
    status: ApprovalStatus
    created_at: datetime
