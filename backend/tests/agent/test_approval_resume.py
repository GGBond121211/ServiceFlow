from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from serviceflow.agent.graph import build_service_graph
from serviceflow.agent.model import ModelResult
from serviceflow.application.case_service import CaseService
from serviceflow.domain.models import Approval, ApprovalStatus, Order, OrderStatus
from serviceflow.domain.results import Decision
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.tables import UserRow


class ApprovalModel:
    def __init__(self, order_id: str) -> None:
        self._order_id = order_id

    def complete_json(self, *, system: str, user: str) -> ModelResult:
        return ModelResult(
            content={
                "order_id": self._order_id,
                "requested_action": "refund",
                "issue_type": "quality",
                "issue_summary": "Product is defective",
                "missing_fields": [],
            },
            model="fake-approval-model",
            input_tokens=10,
            output_tokens=5,
        )


@pytest.fixture
def database(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'approval.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(UserRow(id="USER-001", display_name="Demo User"))
        for order_id in ("ORDER-APPROVE", "ORDER-REJECT"):
            OrderRepository(session).add(
                Order(
                    id=order_id,
                    user_id="USER-001",
                    status=OrderStatus.DELIVERED,
                    total_amount=Decimal("899.00"),
                    placed_at=datetime(2026, 7, 1, tzinfo=UTC),
                    delivered_at=datetime(2026, 7, 30, tzinfo=UTC),
                )
            )
        session.commit()
    yield factory
    engine.dispose()


@pytest.mark.parametrize(
    ("order_id", "approved", "expected_order", "expected_approval"),
    [
        ("ORDER-APPROVE", True, "refunded", "approved"),
        ("ORDER-REJECT", False, "delivered", "rejected"),
    ],
)
def test_high_value_refund_pauses_and_resumes(
    database: sessionmaker[Session],
    order_id: str,
    approved: bool,
    expected_order: str,
    expected_approval: str,
) -> None:
    graph = build_service_graph(
        model=ApprovalModel(order_id),
        session_factory=database,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": order_id}}

    first = graph.invoke(
        {
            "thread_id": order_id,
            "user_id": "USER-001",
            "user_message": f"Refund {order_id}",
            "reference_date": "2026-08-01",
        },
        config=config,
    )

    assert first["decision"] is Decision.APPROVAL_REQUIRED
    assert first["approval_id"]
    assert first["final_business_state"]["approval_status"] == "pending"
    assert first["__interrupt__"]

    resumed = graph.invoke(Command(resume={"approved": approved}), config=config)

    assert resumed["final_business_state"]["order_status"] == expected_order
    assert resumed["final_business_state"]["approval_status"] == expected_approval
    if approved:
        assert resumed["final_business_state"]["refund_status"] == "completed"
    assert resumed["tool_events"][-1]["tool"] == "decide_approval"

    with database() as session:
        approval_id = None
        for event in resumed["tool_events"]:
            if event["tool"] != "create_approval":
                continue
            candidate_id = event["case_id"]
            if candidate_id is not None:
                approval_id = candidate_id
                break
        assert approval_id is not None
        saved = CaseService(session).get_case_status(approval_id)
        service_case = None
        if saved is not None:
            service_case = saved.case
    assert isinstance(service_case, Approval)
    assert service_case.status is ApprovalStatus(expected_approval)
