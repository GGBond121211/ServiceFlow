"""被 `test_durable_session_resume.py` 以**独立进程**拉起的辅助脚本。

存在的理由：同进程里换个 engine 只能证明"换了连接还能读"，证明不了
"进程重启后还能恢复"——模块级缓存、InMemorySaver 残留、事件循环状态
都还在。真正的重启必须换进程。

用法（两段都由测试调用）：

    python _resume_worker.py start  <db_path> <thread_id> <order_id>
    python _resume_worker.py resume <db_path> <thread_id> <approved>

`start` 跑到审批中断就退出；`resume` 在**全新进程**里接着跑完。
两段都只依赖 SQLite 文件，不共享任何内存状态。

文件名以 `_` 开头，pytest 不会把它当测试模块收集。
"""

import asyncio
import json
import sys
from pathlib import Path

from langgraph.types import Command
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from serviceflow.agent.graph import build_service_graph
from serviceflow.agent.model import ModelResult
from serviceflow.infrastructure.checkpoint_store import SqlAlchemyCheckpointSaver


class FixedIntentModel:
    """固定意图的假模型。重启的两段必须用同一个，否则测的是模型而非恢复。"""

    def __init__(self, order_id: str) -> None:
        self._order_id = order_id

    async def complete_json(self, *, system: str, user: str) -> ModelResult:
        del system, user
        return ModelResult(
            content={
                "order_id": self._order_id,
                "requested_action": "refund",
                "issue_type": "quality",
                "issue_summary": "屏幕有坏点",
                "missing_fields": [],
            },
            model="fake-resume-model",
            input_tokens=10,
            output_tokens=5,
        )


def _build(db_path: str, order_id: str):
    engine = create_async_engine(f"sqlite+aiosqlite:///{Path(db_path).as_posix()}")
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    graph = build_service_graph(
        model=FixedIntentModel(order_id),
        session_factory=factory,
        checkpointer=SqlAlchemyCheckpointSaver(factory),
    )
    return engine, graph


async def _start(db_path: str, thread_id: str, order_id: str) -> dict[str, object]:
    engine, graph = _build(db_path, order_id)
    try:
        config = {"configurable": {"thread_id": thread_id}}
        result = await graph.ainvoke(
            {
                "thread_id": thread_id,
                "user_id": "USER-001",
                "user_message": "这个订单我要退款",
                "reference_date": "2026-08-01",
            },
            config,
        )
        snapshot = await graph.aget_state(config)
        return {
            "interrupted": bool(snapshot.next),
            "next": list(snapshot.next),
            "approval_id": result.get("approval_id"),
            "case_id": result.get("case_id"),
        }
    finally:
        await engine.dispose()


async def _resume(db_path: str, thread_id: str, approved: bool) -> dict[str, object]:
    # 注意：这里刻意不传 order_id 给状态——订单号必须来自 checkpoint，
    # 而 checkpoint 只可能来自上一个进程写进 SQLite 的那份。
    engine, graph = _build(db_path, "ORDER-UNUSED")
    try:
        config = {"configurable": {"thread_id": thread_id}}
        result = await graph.ainvoke(Command(resume={"approved": approved}), config)
        snapshot = await graph.aget_state(config)
        return {
            "order_id": result.get("order_id"),
            "final_business_state": result.get("final_business_state"),
            "assistant_message": result.get("assistant_message"),
            "still_interrupted": bool(snapshot.next),
        }
    finally:
        await engine.dispose()


def main() -> None:
    mode = sys.argv[1]
    db_path = sys.argv[2]
    thread_id = sys.argv[3]
    if mode == "start":
        payload = asyncio.run(_start(db_path, thread_id, sys.argv[4]))
    elif mode == "resume":
        payload = asyncio.run(_resume(db_path, thread_id, sys.argv[4] == "true"))
    else:  # pragma: no cover - 调用方拼错了才会到这里
        raise SystemExit(f"unknown mode: {mode}")
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
