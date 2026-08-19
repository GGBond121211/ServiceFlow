from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from serviceflow.domain.models import Order, OrderItem, OrderStatus
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.tables import UserRow


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    database_path = (tmp_path / "serviceflow.db").as_posix()
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        database_session.add(UserRow(id="USER-001", display_name="Demo User"))
        database_session.commit()
        yield database_session
    engine.dispose()


def sample_order() -> Order:
    return Order(
        id="ORDER-001",
        user_id="USER-001",
        status=OrderStatus.PAID,
        total_amount=Decimal("199.00"),
        placed_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC),
        items=(
            OrderItem(
                id="ITEM-001",
                order_id="ORDER-001",
                product_name="Mechanical Keyboard",
                category="electronics",
                unit_price=Decimal("199.00"),
                quantity=1,
            ),
        ),
    )


def test_add_then_get_restores_order(session: Session) -> None:
    repository = OrderRepository(session)
    order = sample_order()

    repository.add(order)
    session.commit()
    session.expire_all()

    assert repository.get(order.id) == order


def test_set_status_persists_change(session: Session) -> None:
    repository = OrderRepository(session)
    repository.add(sample_order())
    session.commit()

    updated = repository.set_status("ORDER-001", OrderStatus.CANCELLED)
    session.commit()
    session.expire_all()

    assert updated.status is OrderStatus.CANCELLED
    assert repository.get("ORDER-001") == updated


def test_get_missing_order_returns_none(session: Session) -> None:
    assert OrderRepository(session).get("ORDER-404") is None
