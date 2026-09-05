"""Run 与 RunSnapshot：模型的一次运行，和它的恢复点。

硬约束：不保存模型隐藏推理，由 _FORBIDDEN_KEYS 在 save_snapshot 里代码级拦截。
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.infrastructure.database import ensure_utc
from serviceflow.infrastructure.tables import AgentRunRow, AgentRunSnapshotRow

# 小写子串匹配：reasoning_content、thinking_blocks、hidden_state 都会被拦。
_FORBIDDEN_KEYS: tuple[str, ...] = (
    "reasoning",
    "thinking",
    "chain_of_thought",
    "cot",
    "scratchpad",
    "hidden",
    "internal_monologue",
)


class HiddenReasoningRejected(ValueError):
    pass


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class Run:
    id: str
    tenant_id: str
    session_id: str
    thread_id: str
    status: RunStatus
    started_at: datetime
    goal_id: str | None = None
    case_id: str | None = None
    operation_id: str | None = None
    finished_at: datetime | None = None
    trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    # resume_point 是"已完成到哪"，next_step 是"接下来打算做什么"。
    # 两者不一致说明上一步崩在写快照之后、执行之前——排查时都要看。
    run_id: str
    state_version: int
    session_id: str
    goal_id: str | None
    case_id: str | None
    operation_id: str | None
    current_goal: str
    confirmed_facts: dict[str, Any]
    candidate_actions: tuple[str, ...]
    tool_summary: tuple[dict[str, Any], ...]
    budget: dict[str, Any]
    deadline: datetime | None
    last_error: str | None
    next_step: str
    resume_point: str
    created_at: datetime
    checkpoint_id: str | None = None


class RunStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start_run(
        self,
        *,
        run_id: str,
        tenant_id: str,
        session_id: str,
        thread_id: str,
        started_at: datetime,
        goal_id: str | None = None,
        case_id: str | None = None,
        operation_id: str | None = None,
        trace_id: str | None = None,
    ) -> Run:
        row = AgentRunRow(
            id=run_id,
            tenant_id=tenant_id,
            session_id=session_id,
            thread_id=thread_id,
            goal_id=goal_id,
            case_id=case_id,
            operation_id=operation_id,
            status=RunStatus.RUNNING.value,
            started_at=started_at,
            trace_id=trace_id,
        )
        self._session.add(row)
        await self._session.flush()
        return _run_to_domain(row)

    async def finish_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        finished_at: datetime,
    ) -> Run:
        row = await self._session.get(AgentRunRow, run_id)
        if row is None:
            raise LookupError("run_not_found")
        row.status = status.value
        row.finished_at = finished_at
        await self._session.flush()
        return _run_to_domain(row)

    async def get_run(self, run_id: str) -> Run | None:
        row = await self._session.get(AgentRunRow, run_id)
        if row is None:
            return None
        return _run_to_domain(row)

    async def runs_for_case(self, case_id: str) -> tuple[Run, ...]:
        rows = await self._session.scalars(
            select(AgentRunRow)
            .where(AgentRunRow.case_id == case_id)
            .order_by(AgentRunRow.started_at)
        )
        return tuple(_run_to_domain(row) for row in rows)

    async def save_snapshot(self, snapshot: RunSnapshot) -> None:
        payload = _snapshot_payload(snapshot)
        _reject_hidden_reasoning(payload)
        self._session.add(
            AgentRunSnapshotRow(
                run_id=snapshot.run_id,
                state_version=snapshot.state_version,
                checkpoint_id=snapshot.checkpoint_id,
                payload=payload,
                created_at=snapshot.created_at,
            )
        )
        await self._session.flush()

    async def latest_snapshot(self, run_id: str) -> RunSnapshot | None:
        row = await self._session.scalar(
            select(AgentRunSnapshotRow)
            .where(AgentRunSnapshotRow.run_id == run_id)
            .order_by(AgentRunSnapshotRow.seq.desc())
            .limit(1)
        )
        if row is None:
            return None
        return _snapshot_to_domain(row)

    async def snapshots(self, run_id: str) -> tuple[RunSnapshot, ...]:
        rows = await self._session.scalars(
            select(AgentRunSnapshotRow)
            .where(AgentRunSnapshotRow.run_id == run_id)
            .order_by(AgentRunSnapshotRow.seq)
        )
        return tuple(_snapshot_to_domain(row) for row in rows)


def _snapshot_payload(snapshot: RunSnapshot) -> dict[str, Any]:
    data = asdict(snapshot)
    # run_id / state_version / checkpoint_id 有独立列，不重复进 payload。
    for key in ("run_id", "state_version", "checkpoint_id", "created_at"):
        data.pop(key, None)
    data["candidate_actions"] = list(snapshot.candidate_actions)
    data["tool_summary"] = [dict(item) for item in snapshot.tool_summary]
    data["deadline"] = snapshot.deadline.isoformat() if snapshot.deadline else None
    return data


def _snapshot_to_domain(row: AgentRunSnapshotRow) -> RunSnapshot:
    payload = dict(row.payload or {})
    deadline = payload.get("deadline")
    return RunSnapshot(
        run_id=row.run_id,
        state_version=row.state_version,
        checkpoint_id=row.checkpoint_id,
        session_id=str(payload.get("session_id", "")),
        goal_id=payload.get("goal_id"),
        case_id=payload.get("case_id"),
        operation_id=payload.get("operation_id"),
        current_goal=str(payload.get("current_goal", "")),
        confirmed_facts=dict(payload.get("confirmed_facts") or {}),
        candidate_actions=tuple(payload.get("candidate_actions") or ()),
        tool_summary=tuple(dict(item) for item in payload.get("tool_summary") or ()),
        budget=dict(payload.get("budget") or {}),
        deadline=datetime.fromisoformat(deadline) if deadline else None,
        last_error=payload.get("last_error"),
        next_step=str(payload.get("next_step", "")),
        resume_point=str(payload.get("resume_point", "")),
        created_at=ensure_utc(row.created_at),
    )


def _run_to_domain(row: AgentRunRow) -> Run:
    return Run(
        id=row.id,
        tenant_id=row.tenant_id,
        session_id=row.session_id,
        thread_id=row.thread_id,
        status=RunStatus(row.status),
        started_at=ensure_utc(row.started_at),
        goal_id=row.goal_id,
        case_id=row.case_id,
        operation_id=row.operation_id,
        finished_at=ensure_utc(row.finished_at),
        trace_id=row.trace_id,
    )


def _reject_hidden_reasoning(payload: Any, path: str = "payload") -> None:
    # 只看键不看值：值里出现"reasoning"是正常的（用户就在问"你的理由是什么"），
    # 键名里出现才是把推理当数据存了。
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            for banned in _FORBIDDEN_KEYS:
                if banned in lowered:
                    raise HiddenReasoningRejected(
                        f"{path}.{key} 命中隐藏推理字段黑名单（{banned}）："
                        f"RunSnapshot 只保存业务事实和恢复点，不保存模型推理过程"
                    )
            _reject_hidden_reasoning(value, f"{path}.{key}")
    elif isinstance(payload, list | tuple):
        for index, item in enumerate(payload):
            _reject_hidden_reasoning(item, f"{path}[{index}]")
