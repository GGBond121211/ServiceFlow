import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

from sqlalchemy import delete
from sqlalchemy.orm import Session

from serviceflow.infrastructure.tables import (
    ApprovalRow,
    OrderItemRow,
    OrderRow,
    RefundRow,
    TicketRow,
    UserRow,
)

DEFAULT_SEED_PATH = Path(__file__).parents[3] / "tests" / "fixtures" / "seed_data.json"


def seed_database(session: Session, fixture_path: Path | None = None) -> None:
    seed_path = fixture_path
    if seed_path is None:
        seed_path = DEFAULT_SEED_PATH
    data = json.loads(seed_path.read_text(encoding="utf-8"))
    users = cast(list[dict[str, object]], data["users"])
    orders = cast(list[dict[str, object]], data["orders"])

    session.execute(delete(ApprovalRow))
    session.execute(delete(TicketRow))
    session.execute(delete(RefundRow))
    session.execute(delete(OrderItemRow))
    session.execute(delete(OrderRow))
    session.execute(delete(UserRow))

    user_rows = []
    for user in users:
        user_id = str(user["id"])
        display_name = str(user["display_name"])
        user_rows.append(UserRow(id=user_id, display_name=display_name))
    session.add_all(user_rows)
    session.flush()
    for order in orders:
        order_id = str(order["id"])
        items = []
        for item in cast(list[dict[str, object]], order["items"]):
            items.append(
                OrderItemRow(
                    id=str(item["id"]),
                    order_id=order_id,
                    product_name=str(item["product_name"]),
                    category=str(item["category"]),
                    unit_price=Decimal(str(item["unit_price"])),
                    quantity=int(str(item["quantity"])),
                )
            )
        row = OrderRow(
            id=order_id,
            user_id=str(order["user_id"]),
            status=str(order["status"]),
            total_amount=Decimal(str(order["total_amount"])),
            placed_at=_parse_datetime(order["placed_at"]),
            delivered_at=_parse_datetime(order["delivered_at"]),
            items=items,
        )
        session.add(row)
    session.commit()


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value))
