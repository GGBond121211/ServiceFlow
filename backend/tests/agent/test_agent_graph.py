from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from serviceflow.agent.graph import build_service_graph
from serviceflow.agent.model import ModelResult
from serviceflow.domain.models import Order, OrderStatus
from serviceflow.domain.results import Decision
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.tables import UserRow


class MappingModel:
    def __init__(self, responses: dict[str, dict[str, object]]) -> None:
        self._responses = responses

    def complete_json(self, *, system: str, user: str) -> ModelResult:
        return ModelResult(
            content=self._responses[user],
            model="fake-graph-model",
            input_tokens=10,
            output_tokens=5,
        )


@pytest.fixture
def database(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    database_path = (tmp_path / "agent.db").as_posix()
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(UserRow(id="USER-001", display_name="Demo User"))
        session.commit()
    yield factory
    engine.dispose()


def add_order(
    factory: sessionmaker[Session],
    *,
    order_id: str,
    status: OrderStatus,
    amount: str,
) -> None:
    with factory() as session:
        delivered_at = None
        if status is OrderStatus.DELIVERED:
            delivered_at = datetime(2026, 7, 30, tzinfo=UTC)
        OrderRepository(session).add(
            Order(
                id=order_id,
                user_id="USER-001",
                status=status,
                total_amount=Decimal(amount),
                placed_at=datetime(2026, 7, 1, tzinfo=UTC),
                delivered_at=delivered_at,
            )
        )
        session.commit()


def invoke_graph(
    factory: sessionmaker[Session],
    *,
    message: str,
    intent: dict[str, object],
) -> dict[str, object]:
    graph = build_service_graph(
        model=MappingModel({message: intent}),
        session_factory=factory,
    )
    return graph.invoke(
        {
            "thread_id": message,
            "user_id": "USER-001",
            "user_message": message,
            "reference_date": "2026-08-01",
        }
    )


def test_paid_order_cancellation_reaches_database(database: sessionmaker[Session]) -> None:
    add_order(database, order_id="ORDER-001", status=OrderStatus.PAID, amount="199.00")
    message = "Cancel ORDER-001"

    result = invoke_graph(
        database,
        message=message,
        intent={
            "order_id": "ORDER-001",
            "requested_action": "cancel",
            "issue_type": "none",
            "issue_summary": "Cancel before shipment",
            "missing_fields": [],
        },
    )

    with database() as session:
        saved = OrderRepository(session).get("ORDER-001")
    assert result["decision"] is Decision.CANCEL
    assert saved is not None and saved.status is OrderStatus.CANCELLED


def test_small_refund_and_exchange_execute_correct_tools(
    database: sessionmaker[Session],
) -> None:
    add_order(database, order_id="ORDER-002", status=OrderStatus.DELIVERED, amount="199.00")
    add_order(database, order_id="ORDER-003", status=OrderStatus.DELIVERED, amount="499.00")

    refund = invoke_graph(
        database,
        message="Refund ORDER-002",
        intent={
            "order_id": "ORDER-002",
            "requested_action": "refund",
            "issue_type": "changed_mind",
            "issue_summary": "Changed mind",
            "missing_fields": [],
        },
    )
    exchange = invoke_graph(
        database,
        message="Exchange ORDER-003",
        intent={
            "order_id": "ORDER-003",
            "requested_action": "exchange",
            "issue_type": "quality",
            "issue_summary": "Product is defective",
            "missing_fields": [],
        },
    )

    assert refund["final_business_state"]["order_status"] == "refunded"
    assert refund["tool_events"][-1]["tool"] == "request_refund"
    assert exchange["final_business_state"]["order_status"] == "ticket_open"
    assert exchange["tool_events"][-1]["tool"] == "create_ticket"


def test_missing_order_id_only_returns_clarification(database: sessionmaker[Session]) -> None:
    result = invoke_graph(
        database,
        message="My headphones are broken",
        intent={
            "order_id": None,
            "requested_action": "refund",
            "issue_type": "quality",
            "issue_summary": "Headphones are broken",
            "missing_fields": ["order_id"],
        },
    )

    assert result["decision"] is Decision.ASK_FOR_INFO
    assert result["tool_events"] == []
    assert "order" in result["assistant_message"].lower()
