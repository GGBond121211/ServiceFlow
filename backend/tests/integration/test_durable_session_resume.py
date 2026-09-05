"""持久化 checkpoint 与跨重启恢复（SQLite）。

对应 Step 2 验收第 1、2 条，以及那条边界：MySQL 业务状态是最终事实，
checkpoint 是恢复上下文，Event Log 是审计，三者不能互相冒充。

**测试成本纪律**：起 subprocess 每次约 7 秒（要重新
import langgraph）。全文件**只起 2 次**，集中在 `cross_process` 这个 module 级
fixture 里——那是唯一无法用同进程证明的事（模块缓存、事件循环状态都还在，
同进程换 engine 证明不了进程重启）。其余测试要么同进程跑图，要么直接调
`aput` 造 checkpoint，都是毫秒级。
"""

import asyncio
import json
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from _resume_worker import FixedIntentModel  # worker 脚本与本文件共用同一个假模型
from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.agent.graph import build_service_graph
from serviceflow.application.session_service import SessionService
from serviceflow.domain.cases import CaseStatus, CaseType, TransitionActor
from serviceflow.domain.models import Order, OrderStatus
from serviceflow.domain.operations import ActionType, OperationStatus, ReplayVerdict
from serviceflow.domain.sessions import Channel
from serviceflow.infrastructure.checkpoint_store import SqlAlchemyCheckpointSaver
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.event_log import EventLog
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.run_store import (
    HiddenReasoningRejected,
    RunSnapshot,
    RunStatus,
    RunStore,
)
from serviceflow.infrastructure.tables import CheckpointRow, RefundRow, UserRow

TENANT = "TENANT-DEMO"
USER = "USER-001"
WORKER = Path(__file__).with_name("_resume_worker.py")


async def seed(database_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        session.add(UserRow(id=USER, display_name="Demo User"))
        for order_id, amount in (("ORDER-HIGH", "899.00"), ("ORDER-LOW", "199.00")):
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
    await engine.dispose()


@pytest_asyncio.fixture
async def database_path(tmp_path: Path) -> AsyncIterator[Path]:
    path = tmp_path / "resume.db"
    await seed(path)
    yield path


@pytest_asyncio.fixture
async def factory(
    database_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    yield async_sessionmaker(bind=engine, expire_on_commit=False)
    await engine.dispose()


def build_graph(factory: async_sessionmaker[AsyncSession], order_id: str):
    return build_service_graph(
        model=FixedIntentModel(order_id),
        session_factory=factory,
        checkpointer=SqlAlchemyCheckpointSaver(factory),
    )


async def run_until_interrupt(
    factory: async_sessionmaker[AsyncSession],
    *,
    thread_id: str,
    order_id: str,
) -> dict[str, object]:
    graph = build_graph(factory, order_id)
    return await graph.ainvoke(
        {
            "thread_id": thread_id,
            "user_id": USER,
            "user_message": "这个订单我要退款",
            "reference_date": "2026-08-01",
        },
        {"configurable": {"thread_id": thread_id}},
    )


async def resume(
    factory: async_sessionmaker[AsyncSession],
    *,
    thread_id: str,
    approved: bool,
) -> dict[str, object]:
    graph = build_graph(factory, "ORDER-UNUSED")
    return await graph.ainvoke(
        Command(resume={"approved": approved}),
        {"configurable": {"thread_id": thread_id}},
    )


# --- 唯一的跨进程证明（2 次 subprocess，全文件仅此处）---------------------


def run_worker(*args: str) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(WORKER), *args],
        capture_output=True,
        text=True,
        cwd=str(WORKER.parents[2]),
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"worker {args} 失败：\nstdout={completed.stdout}\nstderr={completed.stderr}"
        )
    return json.loads(completed.stdout)


@pytest.fixture(scope="module")
def cross_process(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """A 进程跑到审批中断退出，B 进程接着跑完。中间只有 SQLite 文件。

    module 级：这 2 次 subprocess 的结果被下面 4 个测试共享，不重复跑。
    """
    path = tmp_path_factory.mktemp("cross") / "cross.db"
    asyncio.run(seed(path))
    started = run_worker("start", str(path), "THREAD-CROSS", "ORDER-HIGH")
    resumed = run_worker("resume", str(path), "THREAD-CROSS", "true")
    return {"path": path, "started": started, "resumed": resumed}


@pytest_asyncio.fixture
async def cross_factory(
    cross_process: dict[str, object],
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{Path(str(cross_process['path'])).as_posix()}"
    )
    yield async_sessionmaker(bind=engine, expire_on_commit=False)
    await engine.dispose()


def test_first_process_stops_at_the_approval_interrupt(
    cross_process: dict[str, object],
) -> None:
    started = cross_process["started"]
    assert started["interrupted"] is True
    assert started["next"] == ["wait_for_approval"]
    assert str(started["approval_id"]).startswith("APPROVAL-")


def test_second_process_finishes_the_approval(cross_process: dict[str, object]) -> None:
    resumed = cross_process["resumed"]
    assert resumed["still_interrupted"] is False
    # order_id 只可能来自 checkpoint——resume 进程构造图时传的是 ORDER-UNUSED。
    assert resumed["order_id"] == "ORDER-HIGH"
    assert resumed["final_business_state"] == {
        "order_status": OrderStatus.REFUNDED.value,
        "refund_status": "completed",
        "approval_status": "approved",
    }


@pytest.mark.asyncio
async def test_checkpoint_really_reached_disk(
    cross_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with cross_factory() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(CheckpointRow)
            .where(CheckpointRow.thread_id == "THREAD-CROSS")
        )
        refunds = (
            await db.scalars(select(RefundRow).where(RefundRow.order_id == "ORDER-HIGH"))
        ).all()
    assert count is not None and count > 0
    assert len(refunds) == 1
    assert refunds[0].amount == Decimal("899.00")


@pytest.mark.asyncio
async def test_business_truth_wins_over_a_stale_checkpoint(
    cross_factory: async_sessionmaker[AsyncSession],
) -> None:
    saver = SqlAlchemyCheckpointSaver(cross_factory)
    tuple_ = await saver.aget_tuple({"configurable": {"thread_id": "THREAD-CROSS"}})
    assert tuple_ is not None
    snapshot = tuple_.checkpoint["channel_values"]["order_snapshot"]
    # checkpoint 存的是执行前的订单快照，本来就该是旧的。
    assert snapshot["status"] == OrderStatus.DELIVERED.value

    async with cross_factory() as db:
        order = await OrderRepository(db).get("ORDER-HIGH")
    assert order is not None
    assert order.status is OrderStatus.REFUNDED, "数据库才是最终事实"


# --- 审批流程（同进程即可证明，不需要 subprocess）-------------------------


@pytest.mark.asyncio
async def test_resuming_a_finished_thread_does_not_duplicate_the_refund(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await run_until_interrupt(factory, thread_id="THREAD-ONCE", order_id="ORDER-HIGH")
    await resume(factory, thread_id="THREAD-ONCE", approved=True)
    await resume(factory, thread_id="THREAD-ONCE", approved=True)

    async with factory() as db:
        refunds = (
            await db.scalars(select(RefundRow).where(RefundRow.order_id == "ORDER-HIGH"))
        ).all()

    assert len(refunds) == 1, (
        "第二次 resume 产生了重复退款——V1 靠 orders.status 挡住，"
        "Step 7 会换成 Operation 幂等键"
    )


@pytest.mark.asyncio
async def test_rejected_approval_leaves_no_refund(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await run_until_interrupt(factory, thread_id="THREAD-REJECT", order_id="ORDER-HIGH")
    result = await resume(factory, thread_id="THREAD-REJECT", approved=False)

    final = result["final_business_state"]
    assert final["approval_status"] == "rejected"
    assert final["order_status"] == OrderStatus.DELIVERED.value

    async with factory() as db:
        refunds = (
            await db.scalars(select(RefundRow).where(RefundRow.order_id == "ORDER-HIGH"))
        ).all()
    assert refunds == []


@pytest.mark.asyncio
async def test_two_threads_do_not_see_each_others_checkpoints(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await run_until_interrupt(factory, thread_id="THREAD-A", order_id="ORDER-HIGH")
    await run_until_interrupt(factory, thread_id="THREAD-B", order_id="ORDER-LOW")

    saver = SqlAlchemyCheckpointSaver(factory)
    a = [t async for t in saver.alist({"configurable": {"thread_id": "THREAD-A"}})]
    b = [t async for t in saver.alist({"configurable": {"thread_id": "THREAD-B"}})]

    assert a and b
    assert {t.checkpoint["id"] for t in a}.isdisjoint({t.checkpoint["id"] for t in b})
    assert all(
        t.checkpoint["channel_values"].get("order_id") == "ORDER-HIGH"
        for t in a
        if "order_id" in t.checkpoint["channel_values"]
    )


# --- Saver 机制（直接调 aput 造 checkpoint，不跑图）-----------------------


async def put_chain(
    saver: SqlAlchemyCheckpointSaver,
    *,
    thread_id: str,
    count: int,
) -> list[str]:
    """写一条 count 长的父子链，返回 checkpoint id（正序）。"""
    ids: list[str] = []
    config: dict[str, object] = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    for index in range(count):
        checkpoint_id = f"cp-{index:04d}"
        config = await saver.aput(
            config,
            {
                "v": 4,
                "id": checkpoint_id,
                "ts": datetime(2026, 9, 3, tzinfo=UTC).isoformat(),
                "channel_values": {"counter": index},
                "channel_versions": {"counter": str(index)},
                "versions_seen": {},
            },
            {"source": "loop", "step": index},
            {"counter": str(index)},
        )
        ids.append(checkpoint_id)
    return ids


@pytest.mark.asyncio
async def test_parent_chain_is_walkable(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    saver = SqlAlchemyCheckpointSaver(factory)
    ids = await put_chain(saver, thread_id="THREAD-CHAIN", count=5)
    config = {"configurable": {"thread_id": "THREAD-CHAIN"}}

    latest = await saver.aget_tuple(config)
    assert latest is not None
    assert latest.checkpoint["id"] == ids[-1]
    assert latest.checkpoint["channel_values"]["counter"] == 4

    hops = 0
    cursor = latest.parent_config
    while cursor is not None:
        parent = await saver.aget_tuple(cursor)
        assert parent is not None
        cursor = parent.parent_config
        hops += 1
    assert hops == 4


@pytest.mark.asyncio
async def test_alist_is_reverse_ordered_and_supports_limit_and_before(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    saver = SqlAlchemyCheckpointSaver(factory)
    ids = await put_chain(saver, thread_id="THREAD-PAGE", count=5)
    config = {"configurable": {"thread_id": "THREAD-PAGE"}}

    everything = [t async for t in saver.alist(config)]
    assert [t.checkpoint["id"] for t in everything] == sorted(ids, reverse=True)

    limited = [t async for t in saver.alist(config, limit=2)]
    assert [t.checkpoint["id"] for t in limited] == [ids[-1], ids[-2]]

    before = [
        t async for t in saver.alist(config, before={"configurable": {"checkpoint_id": ids[2]}})
    ]
    assert [t.checkpoint["id"] for t in before] == [ids[1], ids[0]]


@pytest.mark.asyncio
async def test_lookup_by_explicit_checkpoint_id(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    saver = SqlAlchemyCheckpointSaver(factory)
    ids = await put_chain(saver, thread_id="THREAD-BYID", count=3)

    fetched = await saver.aget_tuple(
        {
            "configurable": {
                "thread_id": "THREAD-BYID",
                "checkpoint_ns": "",
                "checkpoint_id": ids[1],
            }
        }
    )

    assert fetched is not None
    assert fetched.checkpoint["id"] == ids[1]
    assert fetched.parent_config is not None
    assert fetched.parent_config["configurable"]["checkpoint_id"] == ids[0]


@pytest.mark.asyncio
async def test_alist_filters_by_metadata(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    saver = SqlAlchemyCheckpointSaver(factory)
    await put_chain(saver, thread_id="THREAD-FILTER", count=4)
    config = {"configurable": {"thread_id": "THREAD-FILTER"}}

    matched = [t async for t in saver.alist(config, filter={"step": 2})]

    assert len(matched) == 1
    assert matched[0].checkpoint["id"] == "cp-0002"


@pytest.mark.asyncio
async def test_delete_thread_removes_everything(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    saver = SqlAlchemyCheckpointSaver(factory)
    await put_chain(saver, thread_id="THREAD-DROP", count=3)
    config = {"configurable": {"thread_id": "THREAD-DROP"}}
    assert await saver.aget_tuple(config) is not None

    await saver.adelete_thread("THREAD-DROP")

    assert await saver.aget_tuple(config) is None
    assert [t async for t in saver.alist(config)] == []


@pytest.mark.asyncio
async def test_unknown_thread_returns_none_not_an_error(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    saver = SqlAlchemyCheckpointSaver(factory)
    assert await saver.aget_tuple({"configurable": {"thread_id": "NOPE"}}) is None


@pytest.mark.asyncio
async def test_sync_methods_refuse_instead_of_blocking(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    saver = SqlAlchemyCheckpointSaver(factory)
    with pytest.raises(NotImplementedError):
        saver.get_tuple({"configurable": {"thread_id": "X"}})


@pytest.mark.asyncio
async def test_concurrent_puts_on_one_thread_do_not_corrupt_the_store(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    saver = SqlAlchemyCheckpointSaver(factory)
    base = {"configurable": {"thread_id": "THREAD-RACE", "checkpoint_ns": ""}}

    async def put(index: int) -> None:
        await saver.aput(
            base,
            {
                "v": 4,
                "id": f"cp-{index:04d}",
                "ts": datetime(2026, 9, 3, tzinfo=UTC).isoformat(),
                "channel_values": {"counter": index},
                "channel_versions": {"counter": str(index)},
                "versions_seen": {},
            },
            {"source": "loop", "step": index},
            {"counter": str(index)},
        )

    await asyncio.gather(*[put(i) for i in range(6)])

    listed = [t async for t in saver.alist(base)]
    assert len(listed) == 6
    for item in listed:
        assert "counter" in item.checkpoint["channel_values"]


# --- 五轮会话 + 重启 --------------------------------------------------------


@pytest.mark.asyncio
async def test_five_turn_session_continues_after_a_restart(
    database_path: Path,
) -> None:
    """查询 -> 补信息 -> 确认 -> 操作 -> 查进度，中间换掉整个连接池。"""
    engine_a = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    factory_a = async_sessionmaker(bind=engine_a, expire_on_commit=False)
    service_a = SessionService(factory_a)

    # 第 1 轮：用户只说"我要退款"，没给订单号。
    session = await service_a.start_session(
        tenant_id=TENANT, user_id=USER, channel=Channel.WEB
    )
    goal = await service_a.open_goal(
        session_id=session.id, order_id=None, scene_code="refund", created_by="user"
    )
    assert "order_id" in await service_a.missing_facts_for(goal.id)

    # 第 2 轮：补上订单号。
    await service_a.record_facts(
        goal.id, {"order_id": "ORDER-LOW", "requested_action": "refund"}
    )
    case = await service_a.open_case(
        goal_id=goal.id,
        order_id="ORDER-LOW",
        case_type=CaseType.REFUND,
        reason="不想要了",
        policy_id="POL-REFUND-01",
        policy_version="v1",
    )
    await service_a.transition_case(
        case_id=case.id,
        to_status=CaseStatus.READY_TO_ACT,
        actor=TransitionActor.MODEL,
        expected_version=1,
    )

    # ---- 模拟重启：换 engine、换 service，只留数据库文件 ----
    await engine_a.dispose()
    engine_b = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    factory_b = async_sessionmaker(bind=engine_b, expire_on_commit=False)
    service_b = SessionService(factory_b)
    try:
        located = await service_b.locate_goal(
            session_id=session.id, order_id="ORDER-LOW", scene_code="refund"
        )
        assert located.goal is not None
        assert located.goal.id == goal.id, "重启后必须认回同一个目标"
        assert located.goal.known_facts["order_id"] == "ORDER-LOW"

        reloaded = await service_b.load_case(case.id)
        assert reloaded is not None
        assert reloaded.status is CaseStatus.READY_TO_ACT
        assert reloaded.state_version == 2

        # 第 3 轮：用户确认。
        await service_b.transition_case(
            case_id=case.id,
            to_status=CaseStatus.PENDING_CONFIRMATION,
            actor=TransitionActor.MODEL,
            expected_version=2,
        )
        # 第 4 轮：执行。
        await service_b.transition_case(
            case_id=case.id,
            to_status=CaseStatus.PROCESSING,
            actor=TransitionActor.SYSTEM,
            expected_version=3,
        )
        begin = await service_b.begin_operation(
            case_id=case.id,
            action_type=ActionType.REFUND,
            action_id="ACT-5TURN",
            payload={"order_id": "ORDER-LOW", "amount": Decimal("199.00")},
        )
        assert begin.may_execute is True
        await service_b.finish_operation(
            operation_id=begin.operation.id,
            status=OperationStatus.SUCCEEDED,
            result_code="refund_completed",
        )
        await service_b.transition_case(
            case_id=case.id,
            to_status=CaseStatus.COMPLETED,
            actor=TransitionActor.SYSTEM,
            expected_version=4,
        )
        await service_b.complete_goal(goal.id)

        # 第 5 轮：查进度。
        state = await service_b.final_state(case.id)
        assert state["case_status"] == CaseStatus.COMPLETED.value
        assert state["operations"][0]["status"] == OperationStatus.SUCCEEDED.value

        # 已完成的目标不会被"刚才那个售后"续上。
        after = await service_b.locate_goal(
            session_id=session.id, order_id="ORDER-LOW", scene_code="refund"
        )
        assert after.goal is None

        async with factory_b() as db:
            events = await EventLog(db).read_case(case.id)
        assert [e.event_type for e in events][:1] == ["case_opened"]
        assert "case_transitioned" in {e.event_type for e in events}
        assert len(events) >= 6
    finally:
        await engine_b.dispose()


@pytest.mark.asyncio
async def test_operation_replay_is_visible_across_a_restart(
    database_path: Path,
) -> None:
    """幂等键的效力必须跨重启——不能只在同一个连接池里成立。"""
    engine_a = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    factory_a = async_sessionmaker(bind=engine_a, expire_on_commit=False)
    service_a = SessionService(factory_a)
    session = await service_a.start_session(
        tenant_id=TENANT, user_id=USER, channel=Channel.WEB
    )
    goal = await service_a.open_goal(
        session_id=session.id, order_id="ORDER-LOW", scene_code="refund", created_by="user"
    )
    case = await service_a.open_case(
        goal_id=goal.id,
        order_id="ORDER-LOW",
        case_type=CaseType.REFUND,
        reason="质量问题",
        policy_id="POL-REFUND-01",
        policy_version="v1",
    )
    payload = {"order_id": "ORDER-LOW", "amount": Decimal("199.00")}
    begin = await service_a.begin_operation(
        case_id=case.id,
        action_type=ActionType.REFUND,
        action_id="ACT-ACROSS-RESTART",
        payload=payload,
    )
    await service_a.finish_operation(
        operation_id=begin.operation.id,
        status=OperationStatus.SUCCEEDED,
        result_code="refund_completed",
    )
    await engine_a.dispose()

    engine_b = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    try:
        service_b = SessionService(async_sessionmaker(bind=engine_b, expire_on_commit=False))
        again = await service_b.begin_operation(
            case_id=case.id,
            action_type=ActionType.REFUND,
            action_id="ACT-ACROSS-RESTART",
            payload=payload,
        )
        assert again.verdict is ReplayVerdict.ALREADY_SUCCEEDED
        assert again.may_execute is False
        assert await service_b.count_operations(case.id) == 1
    finally:
        await engine_b.dispose()


# --- Run / RunSnapshot ------------------------------------------------------


@pytest.mark.asyncio
async def test_run_snapshot_round_trip(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SessionService(factory)
    session = await service.start_session(
        tenant_id=TENANT, user_id=USER, channel=Channel.WEB
    )
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)

    async with factory() as db:
        store = RunStore(db)
        run = await store.start_run(
            run_id="RUN-0001",
            tenant_id=TENANT,
            session_id=session.id,
            thread_id="THREAD-RUN",
            started_at=now,
        )
        await store.save_snapshot(
            RunSnapshot(
                run_id=run.id,
                state_version=1,
                session_id=session.id,
                goal_id=None,
                case_id=None,
                operation_id=None,
                checkpoint_id="cp-1",
                current_goal="给 ORDER-LOW 办退款",
                confirmed_facts={"order_id": "ORDER-LOW"},
                candidate_actions=("query_order", "refund"),
                tool_summary=({"tool": "get_order", "ok": True, "code": "ok"},),
                budget={"input_tokens": 4096, "used": 512},
                deadline=now + timedelta(seconds=30),
                last_error=None,
                next_step="evaluate_policy",
                resume_point="after_load_order",
                created_at=now,
            )
        )
        await db.commit()

    async with factory() as db:
        store = RunStore(db)
        latest = await store.latest_snapshot("RUN-0001")
        history = await store.snapshots("RUN-0001")

    assert latest is not None
    assert latest.current_goal == "给 ORDER-LOW 办退款"
    assert latest.candidate_actions == ("query_order", "refund")
    assert latest.budget["used"] == 512
    assert latest.deadline == now + timedelta(seconds=30)
    assert latest.resume_point == "after_load_order"
    assert len(history) == 1


@pytest.mark.asyncio
async def test_run_snapshot_rejects_hidden_reasoning(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """计划原文：不保存模型隐藏推理。这条靠代码挡，不靠自觉。"""
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    async with factory() as db:
        store = RunStore(db)
        await store.start_run(
            run_id="RUN-BAD",
            tenant_id=TENANT,
            session_id="SESSION-X",
            thread_id="THREAD-BAD",
            started_at=now,
        )
        snapshot = RunSnapshot(
            run_id="RUN-BAD",
            state_version=1,
            session_id="SESSION-X",
            goal_id=None,
            case_id=None,
            operation_id=None,
            current_goal="退款",
            confirmed_facts={"reasoning_content": "用户其实是想白拿一台"},
            candidate_actions=(),
            tool_summary=(),
            budget={},
            deadline=None,
            last_error=None,
            next_step="done",
            resume_point="start",
            created_at=now,
        )
        with pytest.raises(HiddenReasoningRejected) as excinfo:
            await store.save_snapshot(snapshot)

    assert "reasoning_content" in str(excinfo.value)


@pytest.mark.asyncio
async def test_run_lifecycle_and_correlation(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SessionService(factory)
    session = await service.start_session(
        tenant_id=TENANT, user_id=USER, channel=Channel.WEB
    )
    goal = await service.open_goal(
        session_id=session.id, order_id="ORDER-LOW", scene_code="refund", created_by="user"
    )
    case = await service.open_case(
        goal_id=goal.id,
        order_id="ORDER-LOW",
        case_type=CaseType.REFUND,
        reason="质量问题",
        policy_id="POL-REFUND-01",
        policy_version="v1",
    )
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)

    async with factory() as db:
        store = RunStore(db)
        await store.start_run(
            run_id="RUN-LINK",
            tenant_id=TENANT,
            session_id=session.id,
            thread_id="THREAD-LINK",
            goal_id=goal.id,
            case_id=case.id,
            started_at=now,
            trace_id="0af7651916cd43dd8448eb211c80319c",
        )
        await store.finish_run(
            "RUN-LINK", status=RunStatus.SUCCEEDED, finished_at=now + timedelta(seconds=3)
        )
        await db.commit()

    async with factory() as db:
        run = await RunStore(db).get_run("RUN-LINK")
        runs_for_case = await RunStore(db).runs_for_case(case.id)

    assert run is not None
    assert run.status is RunStatus.SUCCEEDED
    assert run.case_id == case.id
    assert run.goal_id == goal.id
    assert run.trace_id == "0af7651916cd43dd8448eb211c80319c"
    assert run.finished_at == now + timedelta(seconds=3)
    assert [r.id for r in runs_for_case] == ["RUN-LINK"]
