from sqlalchemy.orm import Session

from serviceflow.domain.models import Order
from serviceflow.infrastructure.repositories import OrderRepository


class OrderService:
    def __init__(self, session: Session) -> None:
        self._orders = OrderRepository(session)

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)
