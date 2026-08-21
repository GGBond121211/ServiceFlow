from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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

    async def complete_json(self, *, system: str, user: str) -> ModelResult:
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


@pytest_asyncio.fixture
async def database(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'approval.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        session.add(UserRow(id="USER-001", display_name="Demo User"))
        for order_id in ("ORDER-APPROVE", "ORDER-REJECT"):
            await OrderRepository(session).add(
                Order(
                    id=order_id,
                    user_id="USER-001",
                    status=OrderStatus.DELIVERED,
                    total_amount=Decimal("899.00"),
                    placed_at=datetime(2026, 7, 1, tzinfo=UTC),
                    delivered_at=datetime(2026, 7, 30, tzinfo=UTC),
                )
            )
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("order_id", "approved", "expected_order", "expected_approval"),
    [
        ("ORDER-APPROVE", True, "refunded", "approved"),
        ("ORDER-REJECT", False, "delivered", "rejected"),
    ],
)
async def test_high_value_refund_pauses_and_resumes(
    database: async_sessionmaker[AsyncSession],
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

    first = await graph.ainvoke(
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

    resumed = await graph.ainvoke(Command(resume={"approved": approved}), config=config)

    assert resumed["final_business_state"]["order_status"] == expected_order
    assert resumed["final_business_state"]["approval_status"] == expected_approval
    if approved:
        assert resumed["final_business_state"]["refund_status"] == "completed"
    assert resumed["tool_events"][-1]["tool"] == "decide_approval"

    async with database() as session:
        approval_id = None
        for event in resumed["tool_events"]:
            if event["tool"] != "create_approval":
                continue
            candidate_id = event["case_id"]
            if candidate_id is not None:
                approval_id = candidate_id
                break
        assert approval_id is not None
        saved = await CaseService(session).get_case_status(approval_id)
        service_case = None
        if saved is not None:
            service_case = saved.case
    assert isinstance(service_case, Approval)
    assert service_case.status is ApprovalStatus(expected_approval)
