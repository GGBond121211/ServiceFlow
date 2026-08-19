import os
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from serviceflow.domain.models import OrderStatus
from serviceflow.infrastructure.database import Base, create_database_engine
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.seed import seed_database
from serviceflow.infrastructure.tables import OrderRow, UserRow

DATABASE_URL = os.getenv("SERVICEFLOW_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL.startswith("mysql+pymysql://"),
    reason="MySQL 冒烟测试需要配置 SERVICEFLOW_DATABASE_URL",
)


def test_mysql_seed_and_order_query() -> None:
    engine = create_database_engine(DATABASE_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        seed_database(session)
        order = OrderRepository(session).get("ORDER-001")
        user_count = session.scalar(select(func.count()).select_from(UserRow))
        order_count = session.scalar(select(func.count()).select_from(OrderRow))

    engine.dispose()

    assert user_count == 3
    assert order_count == 12
    assert order is not None
    assert order.status is OrderStatus.PAID
    assert order.total_amount == Decimal("199.00")
