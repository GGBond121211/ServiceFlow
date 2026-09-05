"""ConversationSession 与 AfterSalesGoal 的持久化。

"""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.domain.sessions import (
    AfterSalesGoal,
    Channel,
    ConversationSession,
    GoalStatus,
    SessionStatus,
)
from serviceflow.infrastructure.database import ensure_utc
from serviceflow.infrastructure.tables import AfterSalesGoalRow, ConversationSessionRow


class SessionStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        session_id: str,
        tenant_id: str,
        user_id: str,
        channel: Channel,
        at: datetime,
    ) -> ConversationSession:
        row = ConversationSessionRow(
            id=session_id,
            tenant_id=tenant_id,
            user_id=user_id,
            channel=channel.value,
            status=SessionStatus.ACTIVE.value,
            created_at=at,
            last_active_at=at,
            summary_version=0,
        )
        self._session.add(row)
        await self._session.flush()
        return _session_to_domain(row)

    async def get(self, session_id: str) -> ConversationSession | None:
        row = await self._session.get(ConversationSessionRow, session_id)
        if row is None:
            return None
        return _session_to_domain(row)

    async def touch(self, session_id: str, *, at: datetime) -> ConversationSession:
        row = await self._session.get(ConversationSessionRow, session_id)
        if row is None:
            raise LookupError("session_not_found")
        row.last_active_at = at
        row.status = SessionStatus.ACTIVE.value
        await self._session.flush()
        return _session_to_domain(row)


class GoalStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        goal_id: str,
        session_id: str,
        tenant_id: str,
        user_id: str,
        scene_code: str | None,
        order_id: str | None,
        required_facts: tuple[str, ...],
        created_by: str,
        at: datetime,
    ) -> AfterSalesGoal:
        row = AfterSalesGoalRow(
            id=goal_id,
            session_id=session_id,
            tenant_id=tenant_id,
            user_id=user_id,
            scene_code=scene_code,
            status=GoalStatus.COLLECTING.value,
            order_id=order_id,
            required_facts=list(required_facts),
            known_facts={} if order_id is None else {"order_id": order_id},
            created_by=created_by,
            created_at=at,
            updated_at=at,
        )
        self._session.add(row)
        await self._session.flush()
        return _goal_to_domain(row)

    async def get(self, goal_id: str) -> AfterSalesGoal | None:
        row = await self._session.get(AfterSalesGoalRow, goal_id)
        if row is None:
            return None
        return _goal_to_domain(row)

    async def open_goals(self, session_id: str) -> tuple[AfterSalesGoal, ...]:
        # 正序有意义：resolve_goal 在同订单多候选时取第一个，也就是最早那个。
        rows = await self._session.scalars(
            select(AfterSalesGoalRow)
            .where(
                AfterSalesGoalRow.session_id == session_id,
                AfterSalesGoalRow.status.in_(
                    [status.value for status in GoalStatus if status.is_open]
                ),
            )
            .order_by(AfterSalesGoalRow.created_at, AfterSalesGoalRow.id)
        )
        return tuple(_goal_to_domain(row) for row in rows)

    async def record_facts(
        self,
        goal_id: str,
        facts: dict[str, str],
        *,
        at: datetime,
    ) -> AfterSalesGoal:
        row = await self._session.get(AfterSalesGoalRow, goal_id)
        if row is None:
            raise LookupError("goal_not_found")
        merged = dict(row.known_facts or {})
        merged.update({key: str(value) for key, value in facts.items()})
        # JSON 列必须整体赋新对象：原地改字典 SQLAlchemy 检测不到变更。
        row.known_facts = merged
        if row.order_id is None and merged.get("order_id"):
            row.order_id = merged["order_id"]
        row.updated_at = at
        await self._session.flush()
        return _goal_to_domain(row)

    async def set_status(
        self,
        goal_id: str,
        status: GoalStatus,
        *,
        at: datetime,
    ) -> AfterSalesGoal:
        row = await self._session.get(AfterSalesGoalRow, goal_id)
        if row is None:
            raise LookupError("goal_not_found")
        row.status = status.value
        row.updated_at = at
        if status in (GoalStatus.COMPLETED, GoalStatus.ABANDONED):
            row.completed_at = at
        await self._session.flush()
        return _goal_to_domain(row)

    async def attach_case(
        self,
        goal_id: str,
        case_id: str,
        *,
        at: datetime,
    ) -> AfterSalesGoal:
        row = await self._session.get(AfterSalesGoalRow, goal_id)
        if row is None:
            raise LookupError("goal_not_found")
        if row.case_id is not None and row.case_id != case_id:
            # "一个 Goal 不能被无声地改成另一个案件"在持久层的落点。
            raise ValueError(
                f"目标 {goal_id} 已绑定案件 {row.case_id}，不能改绑到 {case_id}；"
                f"新案件需要新目标"
            )
        row.case_id = case_id
        row.status = GoalStatus.ACTIVE.value
        row.updated_at = at
        await self._session.flush()
        return _goal_to_domain(row)


def _session_to_domain(row: ConversationSessionRow) -> ConversationSession:
    return ConversationSession(
        id=row.id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        channel=Channel(row.channel),
        status=SessionStatus(row.status),
        created_at=ensure_utc(row.created_at),
        last_active_at=ensure_utc(row.last_active_at),
        summary_version=row.summary_version,
    )


def _goal_to_domain(row: AfterSalesGoalRow) -> AfterSalesGoal:
    known: dict[str, Any] = dict(row.known_facts or {})
    return AfterSalesGoal(
        id=row.id,
        session_id=row.session_id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        scene_code=row.scene_code,
        status=GoalStatus(row.status),
        order_id=row.order_id,
        required_facts=tuple(row.required_facts or ()),
        known_facts={key: str(value) for key, value in known.items()},
        case_id=row.case_id,
        created_by=row.created_by,
        created_at=ensure_utc(row.created_at),
        updated_at=ensure_utc(row.updated_at),
        completed_at=ensure_utc(row.completed_at),
    )
