from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from serviceflow.domain.models import Order, OrderItem, OrderStatus
from serviceflow.infrastructure.tables import OrderItemRow, OrderRow


class OrderRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, order_id: str) -> Order | None:
        statement = (
            select(OrderRow).where(OrderRow.id == order_id).options(selectinload(OrderRow.items))
        )
        row = self._session.scalar(statement)
        if row is None:
            return None
        return _to_domain(row)

    def add(self, order: Order) -> None:
        items = []
        for item in order.items:
            items.append(
                OrderItemRow(
                    id=item.id,
                    order_id=item.order_id,
                    product_name=item.product_name,
                    category=item.category,
                    unit_price=item.unit_price,
                    quantity=item.quantity,
                )
            )
        self._session.add(
            OrderRow(
                id=order.id,
                user_id=order.user_id,
                status=order.status.value,
                total_amount=order.total_amount,
                placed_at=order.placed_at,
                delivered_at=order.delivered_at,
                items=items,
            )
        )
        self._session.flush()

    def set_status(self, order_id: str, status: OrderStatus) -> Order:
        row = self._session.get(OrderRow, order_id)
        if row is None:
            raise LookupError("order_not_found")
        row.status = status.value
        self._session.flush()
        updated = self.get(order_id)
        if updated is None:
            raise LookupError("order_not_found")
        return updated


def _to_domain(row: OrderRow) -> Order:
    items = []
    for item in row.items:
        items.append(
            OrderItem(
                id=item.id,
                order_id=item.order_id,
                product_name=item.product_name,
                category=item.category,
                unit_price=item.unit_price,
                quantity=item.quantity,
            )
        )
    return Order(
        id=row.id,
        user_id=row.user_id,
        status=OrderStatus(row.status),
        total_amount=row.total_amount,
        placed_at=_with_utc(row.placed_at),
        delivered_at=_with_utc(row.delivered_at),
        items=tuple(items),
    )


def _with_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)
