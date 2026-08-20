from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.domain.models import Order
from serviceflow.infrastructure.repositories import OrderRepository


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self._orders = OrderRepository(session)

    async def get_order(self, order_id: str) -> Order | None:
        return await self._orders.get(order_id)
