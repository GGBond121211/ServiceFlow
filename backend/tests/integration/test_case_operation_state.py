"""Session / Goal / Case / Operation 的持久化与关联测试（SQLite）。

对应 Step 2 验收第 2、3 条：
- 已完成 Operation 再次进来不重复产生副作用；状态版本冲突返回可解释的冲突结果。
- 数据库、事件里的 caseId / operationId 能互相关联。
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.application.session_service import SessionService
from serviceflow.domain.cases import (
    CaseStatus,
    CaseType,
    TransitionActor,
    TransitionRejection,
)
from serviceflow.domain.models import Order, OrderStatus
from serviceflow.domain.operations import (
    ActionType,
    ErrorClass,
    OperationStatus,
    ReplayVerdict,
)
from serviceflow.domain.sessions import Channel, GoalResolution, GoalStatus
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.event_log import EventLog
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.tables import UserRow

TENANT = "TENANT-DEMO"
USER = "USER-001"


@pytest_asyncio.fixture
async def factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'step2.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(UserRow(id=USER, display_name="Demo User"))
        for order_id, amount in (("ORDER-001", "199.00"), ("ORDER-002", "899.00")):
            await OrderRepository(session).add(
                Order(
                    id=order_id,
                    user_id=USER,
                    status=OrderStatus.DELIVERED,
                    total_amount=Decimal(amount),
                    placed_at=datetime(2026, 7, 1, tzinfo=UTC),
                    delivered_at=datetime(2026, 7, 28, tzinfo=UTC),
                )
            )
        await session.commit()
    yield session_factory
    await engine.dispose()


async def open_case(
    service: SessionService,
    *,
    order_id: str = "ORDER-001",
    scene_code: str = "refund",
) -> tuple[str, str, str]:
    """建一条 session -> goal -> case 链，返回三个 id。"""
    session = await service.start_session(tenant_id=TENANT, user_id=USER, channel=Channel.WEB)
    goal = await service.open_goal(
        session_id=session.id,
        order_id=order_id,
        scene_code=scene_code,
        created_by="user",
    )
    case = await service.open_case(
        goal_id=goal.id,
        order_id=order_id,
        case_type=CaseType.REFUND,
        reason="收到的商品有质量问题",
        policy_id="POL-REFUND-01",
        policy_version="v1",
    )
    return session.id, goal.id, case.id


# --- 持久化往返 -------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_goal_case_round_trip(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SessionService(factory)
    session_id, goal_id, case_id = await open_case(service)

    reloaded_session = await service.load_session(session_id)
    reloaded_goal = await service.load_goal(goal_id)
    reloaded_case = await service.load_case(case_id)

    assert reloaded_session is not None
    assert reloaded_session.tenant_id == TENANT
    assert reloaded_session.channel is Channel.WEB

    assert reloaded_goal is not None
    assert reloaded_goal.session_id == session_id
    assert reloaded_goal.case_id == case_id
    assert reloaded_goal.status is GoalStatus.ACTIVE

    assert reloaded_case is not None
    assert reloaded_case.goal_id == goal_id
    assert reloaded_case.status is CaseStatus.CASE_OPEN
    assert reloaded_case.state_version == 1
    assert reloaded_case.policy_version == "v1"


@pytest.mark.asyncio
async def test_required_facts_come_from_policies_not_the_model(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SessionService(factory)
    session = await service.start_session(tenant_id=TENANT, user_id=USER, channel=Channel.WEB)
    goal = await service.open_goal(
        session_id=session.id,
        order_id=None,
        scene_code="exchange",
        created_by="user",
    )

    assert "order_id" in goal.required_facts
    assert "issue_type" in goal.required_facts, "换货场景必须问清质量问题，这条来自 policies.py"
    assert await service.missing_facts_for(goal.id) == goal.required_facts

    updated = await service.record_facts(goal.id, {"order_id": "ORDER-001"})
    assert updated.known_facts["order_id"] == "ORDER-001"
    assert "order_id" not in await service.missing_facts_for(goal.id)


@pytest.mark.asyncio
async def test_timeline_is_persisted_in_order(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SessionService(factory)
    _, _, case_id = await open_case(service)

    for target, actor in (
        (CaseStatus.WAITING_INFO, TransitionActor.MODEL),
        (CaseStatus.READY_TO_ACT, TransitionActor.MODEL),
        (CaseStatus.PROCESSING, TransitionActor.SYSTEM),
    ):
        case = await service.load_case(case_id)
        assert case is not None
        outcome = await service.transition_case(
            case_id=case_id,
            to_status=target,
            actor=actor,
            expected_version=case.state_version,
            note=f"到 {target.value}",
        )
        assert outcome.ok is True, outcome.reason

    final = await service.load_case(case_id)
    assert final is not None
    assert final.status is CaseStatus.PROCESSING
    assert final.state_version == 4
    assert [entry.to_status for entry in final.timeline] == [
        CaseStatus.WAITING_INFO,
        CaseStatus.READY_TO_ACT,
        CaseStatus.PROCESSING,
    ]
    assert [entry.actor for entry in final.timeline] == [
        TransitionActor.MODEL,
        TransitionActor.MODEL,
        TransitionActor.SYSTEM,
    ]


# --- 状态版本冲突 -----------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_state_version_returns_explainable_conflict(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """两个并发请求读到同一版本，第二个必须被拒且**说清为什么**。"""
    service = SessionService(factory)
    _, _, case_id = await open_case(service)

    first = await service.transition_case(
        case_id=case_id,
        to_status=CaseStatus.WAITING_INFO,
        actor=TransitionActor.MODEL,
        expected_version=1,
    )
    assert first.ok is True

    second = await service.transition_case(
        case_id=case_id,
        to_status=CaseStatus.READY_TO_ACT,
        actor=TransitionActor.MODEL,
        expected_version=1,
    )

    assert second.ok is False
    assert second.rejection is TransitionRejection.STALE_STATE_VERSION
    assert "1" in second.reason and "2" in second.reason

    unchanged = await service.load_case(case_id)
    assert unchanged is not None
    assert unchanged.status is CaseStatus.WAITING_INFO
    assert unchanged.state_version == 2


@pytest.mark.asyncio
async def test_model_cannot_write_a_business_outcome_through_the_service(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """领域层的权限判定必须在服务层也生效，不能只在纯函数里成立。"""
    service = SessionService(factory)
    _, _, case_id = await open_case(service)
    await service.transition_case(
        case_id=case_id,
        to_status=CaseStatus.READY_TO_ACT,
        actor=TransitionActor.MODEL,
        expected_version=1,
    )
    await service.transition_case(
        case_id=case_id,
        to_status=CaseStatus.PROCESSING,
        actor=TransitionActor.SYSTEM,
        expected_version=2,
    )

    outcome = await service.transition_case(
        case_id=case_id,
        to_status=CaseStatus.COMPLETED,
        actor=TransitionActor.MODEL,
        expected_version=3,
    )

    assert outcome.ok is False
    assert outcome.rejection is TransitionRejection.ACTOR_NOT_PERMITTED
    persisted = await service.load_case(case_id)
    assert persisted is not None
    assert persisted.status is CaseStatus.PROCESSING


# --- Operation 幂等 ---------------------------------------------------------


@pytest.mark.asyncio
async def test_same_action_id_replays_instead_of_executing_again(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SessionService(factory)
    _, _, case_id = await open_case(service)
    payload = {"order_id": "ORDER-001", "amount": Decimal("199.00")}

    first = await service.begin_operation(
        case_id=case_id,
        action_type=ActionType.REFUND,
        action_id="ACT-REFUND-1",
        payload=payload,
    )
    assert first.verdict is ReplayVerdict.FIRST_ATTEMPT
    assert first.may_execute is True

    await service.finish_operation(
        operation_id=first.operation.id,
        status=OperationStatus.SUCCEEDED,
        result_code="refund_completed",
    )

    second = await service.begin_operation(
        case_id=case_id,
        action_type=ActionType.REFUND,
        action_id="ACT-REFUND-1",
        payload=payload,
    )

    assert second.verdict is ReplayVerdict.ALREADY_SUCCEEDED
    assert second.may_execute is False
    assert second.operation.id == first.operation.id, "重放必须返回同一条 Operation"
    assert second.operation.attempt == 1, "重放不能增加尝试次数"
    assert await service.count_operations(case_id) == 1


@pytest.mark.asyncio
async def test_same_action_id_with_a_bigger_amount_is_refused(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """幂等键复用 + 改金额：最危险的重放，必须拒绝且不留新记录。"""
    service = SessionService(factory)
    _, _, case_id = await open_case(service)

    first = await service.begin_operation(
        case_id=case_id,
        action_type=ActionType.REFUND,
        action_id="ACT-REFUND-2",
        payload={"order_id": "ORDER-001", "amount": Decimal("199.00")},
    )
    await service.finish_operation(
        operation_id=first.operation.id,
        status=OperationStatus.SUCCEEDED,
        result_code="refund_completed",
    )

    tampered = await service.begin_operation(
        case_id=case_id,
        action_type=ActionType.REFUND,
        action_id="ACT-REFUND-2",
        payload={"order_id": "ORDER-001", "amount": Decimal("19900.00")},
    )

    assert tampered.verdict is ReplayVerdict.FINGERPRINT_MISMATCH
    assert tampered.may_execute is False
    assert await service.count_operations(case_id) == 1


@pytest.mark.asyncio
async def test_failed_operation_can_be_retried_with_a_new_attempt(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SessionService(factory)
    _, _, case_id = await open_case(service)
    payload = {"order_id": "ORDER-001"}

    first = await service.begin_operation(
        case_id=case_id,
        action_type=ActionType.CREATE_SUPPORT_TICKET,
        action_id="ACT-TICKET-1",
        payload=payload,
    )
    await service.finish_operation(
        operation_id=first.operation.id,
        status=OperationStatus.FAILED,
        result_code="provider_unavailable",
        error_class=ErrorClass.PROVIDER_ERROR,
    )

    retry = await service.begin_operation(
        case_id=case_id,
        action_type=ActionType.CREATE_SUPPORT_TICKET,
        action_id="ACT-TICKET-1",
        payload=payload,
    )

    assert retry.verdict is ReplayVerdict.RETRYABLE
    assert retry.may_execute is True
    assert retry.operation.id == first.operation.id
    assert retry.operation.attempt == 2
    assert retry.operation.status is OperationStatus.DISPATCHED
    assert await service.count_operations(case_id) == 1


@pytest.mark.asyncio
async def test_timed_out_operation_needs_reconcile_not_retry(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SessionService(factory)
    _, _, case_id = await open_case(service)
    payload = {"order_id": "ORDER-002", "amount": Decimal("899.00")}

    first = await service.begin_operation(
        case_id=case_id,
        action_type=ActionType.REFUND,
        action_id="ACT-REFUND-3",
        payload=payload,
    )
    await service.finish_operation(
        operation_id=first.operation.id,
        status=OperationStatus.UNKNOWN,
        result_code="gateway_timeout",
        error_class=ErrorClass.TIMEOUT,
    )

    again = await service.begin_operation(
        case_id=case_id,
        action_type=ActionType.REFUND,
        action_id="ACT-REFUND-3",
        payload=payload,
    )

    assert again.verdict is ReplayVerdict.NEEDS_RECONCILE
    assert again.may_execute is False
    assert again.operation.attempt == 1, "对账前不允许把它算作新一次尝试"


@pytest.mark.asyncio
async def test_concurrent_identical_requests_create_one_operation(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """数据库唯一键是最后一道防线：并发下也只能有一条 Operation。"""
    service = SessionService(factory)
    _, _, case_id = await open_case(service)
    payload = {"order_id": "ORDER-001", "amount": Decimal("199.00")}

    results = await asyncio.gather(
        *[
            service.begin_operation(
                case_id=case_id,
                action_type=ActionType.REFUND,
                action_id="ACT-REFUND-RACE",
                payload=payload,
            )
            for _ in range(8)
        ]
    )

    assert await service.count_operations(case_id) == 1
    assert len({r.operation.id for r in results}) == 1
    assert sum(1 for r in results if r.verdict is ReplayVerdict.FIRST_ATTEMPT) == 1
    assert all(
        r.verdict in (ReplayVerdict.FIRST_ATTEMPT, ReplayVerdict.IN_FLIGHT) for r in results
    )


# --- 事件日志与关联 ---------------------------------------------------------


@pytest.mark.asyncio
async def test_event_log_links_case_and_operation(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SessionService(factory)
    session_id, goal_id, case_id = await open_case(service)
    begin = await service.begin_operation(
        case_id=case_id,
        action_type=ActionType.REFUND,
        action_id="ACT-REFUND-4",
        payload={"order_id": "ORDER-001"},
    )
    await service.finish_operation(
        operation_id=begin.operation.id,
        status=OperationStatus.SUCCEEDED,
        result_code="refund_completed",
    )

    async with factory() as db:
        events = await EventLog(db).read_case(case_id)

    types = [event.event_type for event in events]
    assert "case_opened" in types
    assert "operation_requested" in types
    assert "operation_finished" in types
    assert [event.seq for event in events] == sorted(event.seq for event in events)
    for event in events:
        assert event.tenant_id == TENANT
        assert event.case_id == case_id
    finished = next(e for e in events if e.event_type == "operation_finished")
    assert finished.operation_id == begin.operation.id
    assert finished.payload["result_code"] == "refund_completed"

    async with factory() as db:
        session_events = await EventLog(db).read_session(session_id)
    assert any(e.event_type == "session_started" for e in session_events)
    assert any(e.goal_id == goal_id for e in session_events)


@pytest.mark.asyncio
async def test_event_log_is_append_only(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """审计记录不提供改和删。这条测的是**接口面**，不是运行时权限。"""
    async with factory() as db:
        log = EventLog(db)
        for name in ("update", "delete", "purge", "truncate"):
            assert not hasattr(log, name), f"EventLog 不应暴露 {name}"


@pytest.mark.asyncio
async def test_final_state_is_read_from_the_database(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """验收第 3 条：最终响应不能只依据模型文字。"""
    service = SessionService(factory)
    _, _, case_id = await open_case(service)
    begin = await service.begin_operation(
        case_id=case_id,
        action_type=ActionType.REFUND,
        action_id="ACT-REFUND-5",
        payload={"order_id": "ORDER-001"},
    )
    await service.finish_operation(
        operation_id=begin.operation.id,
        status=OperationStatus.SUCCEEDED,
        result_code="refund_completed",
    )

    state = await service.final_state(case_id)

    assert state["case_id"] == case_id
    assert state["case_status"] == CaseStatus.CASE_OPEN.value
    assert state["order_id"] == "ORDER-001"
    assert state["order_status"] == OrderStatus.DELIVERED.value
    assert state["operations"] == [
        {
            "operation_id": begin.operation.id,
            "action_type": ActionType.REFUND.value,
            "status": OperationStatus.SUCCEEDED.value,
            "result_code": "refund_completed",
            "attempt": 1,
        }
    ]


# --- Goal 归属在持久层也成立 ------------------------------------------------


@pytest.mark.asyncio
async def test_second_order_in_the_same_session_opens_a_second_goal(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SessionService(factory)
    session = await service.start_session(tenant_id=TENANT, user_id=USER, channel=Channel.WEB)
    first = await service.open_goal(
        session_id=session.id, order_id="ORDER-001", scene_code="refund", created_by="user"
    )

    located = await service.locate_goal(
        session_id=session.id, order_id="ORDER-002", scene_code="refund"
    )
    assert located.resolution is GoalResolution.NEW_GOAL

    second = await service.open_goal(
        session_id=session.id, order_id="ORDER-002", scene_code="refund", created_by="user"
    )
    assert second.id != first.id

    ambiguous = await service.locate_goal(
        session_id=session.id, order_id=None, scene_code=None
    )
    assert ambiguous.resolution is GoalResolution.AMBIGUOUS
    assert {goal.id for goal in ambiguous.candidates} == {first.id, second.id}


@pytest.mark.asyncio
async def test_completed_goal_is_not_resumed(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SessionService(factory)
    session = await service.start_session(tenant_id=TENANT, user_id=USER, channel=Channel.WEB)
    goal = await service.open_goal(
        session_id=session.id, order_id="ORDER-001", scene_code="refund", created_by="user"
    )
    await service.complete_goal(goal.id)

    located = await service.locate_goal(
        session_id=session.id, order_id="ORDER-001", scene_code="refund"
    )

    assert located.resolution is GoalResolution.NEW_GOAL
    reloaded = await service.load_goal(goal.id)
    assert reloaded is not None
    assert reloaded.status is GoalStatus.COMPLETED
    assert reloaded.completed_at is not None
