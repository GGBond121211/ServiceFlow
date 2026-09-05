"""ConversationSession 与 AfterSalesGoal。纯函数，无 I/O。

核心不变量：一个 Goal 不能被无声地改成另一个案件。resolve_goal 是这条规则的唯一落点。
设计论证见 docs/2.0-WORKLOG.md「Step 2」。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Channel(StrEnum):
    WEB = "web"
    APP = "app"
    CLI = "cli"
    EVAL = "eval"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    IDLE = "idle"
    CLOSED = "closed"


class GoalStatus(StrEnum):
    COLLECTING = "collecting"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    ABANDONED = "abandoned"

    @property
    def is_open(self) -> bool:
        return self in (GoalStatus.COLLECTING, GoalStatus.ACTIVE, GoalStatus.BLOCKED)


class GoalResolution(StrEnum):
    CONTINUE = "continue"
    NEW_GOAL = "new_goal"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class ConversationSession:
    id: str
    tenant_id: str
    user_id: str
    channel: Channel
    status: SessionStatus
    created_at: datetime
    last_active_at: datetime
    summary_version: int = 0


@dataclass(frozen=True, slots=True)
class AfterSalesGoal:
    id: str
    session_id: str
    tenant_id: str
    user_id: str
    # scene_code 为 None 表示这一轮没识别出场景。
    scene_code: str | None
    status: GoalStatus
    order_id: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    # required_facts 由 policies.required_facts_for 给出；known_facts 只存业务事实。
    required_facts: tuple[str, ...] = ()
    known_facts: dict[str, str] = field(default_factory=dict)
    case_id: str | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GoalResolutionOutcome:
    resolution: GoalResolution
    reason: str
    goal: AfterSalesGoal | None = None
    # 只在 AMBIGUOUS 时非空——Agent 需要把这些选项摆给用户。
    candidates: tuple[AfterSalesGoal, ...] = ()


def missing_facts(goal: AfterSalesGoal) -> tuple[str, ...]:
    # 空字符串不算已知：否则模型填个空值就能骗过澄清逻辑。
    return tuple(
        key
        for key in goal.required_facts
        if not str(goal.known_facts.get(key, "")).strip()
    )


def resolve_goal(
    *,
    open_goals: tuple[AfterSalesGoal, ...],
    order_id: str | None,
    scene_code: str | None,
) -> GoalResolutionOutcome:
    # 再过滤一次 is_open：调用方传错时"已完成的案子被续上"是静默的严重错误。
    live = tuple(goal for goal in open_goals if goal.status.is_open)
    if not live:
        return GoalResolutionOutcome(
            resolution=GoalResolution.NEW_GOAL,
            reason="会话中没有未结束的售后目标，开启新目标",
        )

    if order_id is not None:
        same_order = tuple(
            goal for goal in live if goal.order_id is None or goal.order_id == order_id
        )
        if not same_order:
            return GoalResolutionOutcome(
                resolution=GoalResolution.NEW_GOAL,
                reason=f"订单 {order_id} 与所有未结束目标都不同，开启新目标",
            )
        matched = _match_scene(same_order, scene_code)
        if matched is None:
            return GoalResolutionOutcome(
                resolution=GoalResolution.NEW_GOAL,
                reason=(
                    f"订单 {order_id} 已有未结束目标，但 scene 由 "
                    f"{same_order[0].scene_code} 变为 {scene_code}，"
                    f"属于新案件而非改写原目标"
                ),
            )
        return GoalResolutionOutcome(
            resolution=GoalResolution.CONTINUE,
            reason=f"订单 {order_id} 命中未结束目标 {matched.id}",
            goal=matched,
        )

    if len(live) == 1:
        return GoalResolutionOutcome(
            resolution=GoalResolution.CONTINUE,
            reason=f"会话中只有一个未结束目标 {live[0].id}，继续该目标",
            goal=live[0],
        )

    return GoalResolutionOutcome(
        resolution=GoalResolution.AMBIGUOUS,
        reason=(
            f"会话中有 {len(live)} 个未结束目标且本轮未给出订单号，"
            f"无法判断指向哪一个，必须回问用户"
        ),
        candidates=live,
    )


def _match_scene(
    goals: tuple[AfterSalesGoal, ...], scene_code: str | None
) -> AfterSalesGoal | None:
    # scene_code 为 None 时不能开新目标，否则用户说句"那个怎么样了"就丢上下文。
    if scene_code is None:
        return goals[0]
    for goal in goals:
        if goal.scene_code is None or goal.scene_code == scene_code:
            return goal
    return None
