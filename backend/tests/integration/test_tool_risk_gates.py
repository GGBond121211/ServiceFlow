from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.application.case_service import CaseService
from serviceflow.domain.models import Order, OrderStatus
from serviceflow.domain.policy_documents import PolicyDocument
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.qdrant_policy_store import ExactPolicyStore, PolicyRetriever
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.tables import UserRow
from serviceflow.infrastructure.tool_executor import ToolExecutionContext, ToolExecutor


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'tool.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                UserRow(id="USER-001", display_name="User 1"),
                UserRow(id="USER-002", display_name="User 2"),
            ]
        )
        await OrderRepository(session).add(
            Order(
                id="ORDER-001",
                user_id="USER-001",
                status=OrderStatus.DELIVERED,
                total_amount=Decimal("800.00"),
                placed_at=datetime(2026, 7, 1, tzinfo=UTC),
                delivered_at=datetime(2026, 7, 30, tzinfo=UTC),
            )
        )
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_executor_rejects_cross_user_order(database) -> None:
    async with database() as session:
        result = await ToolExecutor(session, tenant_id="tenant-a").execute(
            call_id="call-1",
            name="get_order",
            arguments={"order_id": "ORDER-001"},
            context=ToolExecutionContext("USER-002", "tenant-a"),
        )

    assert result.code == "unauthorized"


@pytest.mark.asyncio
async def test_executor_requires_confirmation_before_refund(database) -> None:
    async with database() as session:
        result = await ToolExecutor(session, tenant_id="tenant-a").execute(
            call_id="call-1",
            name="request_refund",
            arguments={"order_id": "ORDER-001"},
            context=ToolExecutionContext("USER-001", "tenant-a"),
        )

    assert result.code == "confirmation_required"


@pytest.mark.asyncio
async def test_executor_requires_approval_after_confirmation(database) -> None:
    async with database() as session:
        result = await ToolExecutor(session, tenant_id="tenant-a").execute(
            call_id="call-1",
            name="request_refund",
            arguments={"order_id": "ORDER-001"},
            context=ToolExecutionContext("USER-001", "tenant-a", confirmed=True),
        )

    assert result.code == "approval_required"


@pytest.mark.asyncio
async def test_case_lookup_checks_owner_and_returns_no_cross_user_data(database) -> None:
    async with database() as session:
        ticket = await CaseService(session).create_ticket("ORDER-001", "support", "咨询")
        executor = ToolExecutor(session, tenant_id="tenant-a")
        denied = await executor.execute(
            call_id="case", name="get_case", arguments={"case_id": ticket.case.id},
            context=ToolExecutionContext("USER-002", "tenant-a"),
        )
        allowed = await executor.execute(
            call_id="case", name="get_case", arguments={"case_id": ticket.case.id},
            context=ToolExecutionContext("USER-001", "tenant-a"),
        )
        assert denied.code == "unauthorized"
        assert denied.data == {}
        assert allowed.data["order_id"] == "ORDER-001"
        assert allowed.data["case_status"] == "open"


@pytest.mark.asyncio
async def test_unknown_eligibility_action_returns_validation_error(database) -> None:
    async with database() as session:
        result = await ToolExecutor(session, tenant_id="tenant-a").execute(
            call_id="eligibility", name="check_after_sales_eligibility",
            arguments={"order_id": "ORDER-001", "requested_action": "invented"},
            context=ToolExecutionContext("USER-001", "tenant-a"),
        )
        assert result.code == "validation_error"


@pytest.mark.asyncio
@pytest.mark.parametrize("issue,expected", [
    ("none", "action_not_supported"),
    ("invented", "validation_error"),
    ("quality", "ticket_created"),
])
async def test_exchange_requires_supported_quality_issue(database, issue, expected) -> None:
    async with database() as session:
        result = await ToolExecutor(session, tenant_id="tenant-a").execute(
            call_id="exchange", name="create_exchange_request",
            arguments={"order_id": "ORDER-001", "issue_type": issue},
            context=ToolExecutionContext("USER-001", "tenant-a", confirmed=True),
        )
        assert result.code == expected
        if expected != "ticket_created":
            order = await CaseService(session).get_order("ORDER-001")
            assert order.status is OrderStatus.DELIVERED


@pytest.mark.asyncio
async def test_policy_tool_exposes_body_and_provenance(database) -> None:
    document = PolicyDocument.from_mapping({
        "policy_id": "POL-REFUND", "version": "v1", "title": "退款政策",
        "content": "退款须在签收后七天内申请。", "effective_from": "2026-01-01",
        "source_type": "internal", "source_title": "模拟商城政策",
        "source_url": "local://policy", "source_locator": "第1条",
    })
    retriever = PolicyRetriever(ExactPolicyStore((document,)), None)
    async with database() as session:
        result = await ToolExecutor(
            session, tenant_id="tenant-a", policy_retriever=retriever
        ).execute(
            call_id="policy", name="search_policy_evidence",
            arguments={"query": "退款政策"},
            context=ToolExecutionContext(
                "USER-001", "tenant-a", reference_date=date(2026, 8, 1)
            ),
        )
    assert result.ok
    evidence = result.data["evidence"][0]
    assert document.content in evidence
    assert "v1" in evidence and "模拟商城政策 第1条" in evidence
