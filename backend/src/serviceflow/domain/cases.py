"""AfterSalesCase 及其状态机。纯函数，无 I/O。

状态转换保持为纯函数，便于重复测试。
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType


class CaseType(StrEnum):
    # 与 RequestedAction 的区别：那是"用户这句话要干什么"，这是"这个案子在办什么"。
    # 一个案子只有一个类型，换类型就是新案子。
    QUERY = "query"
    CANCEL = "cancel"
    REFUND = "refund"
    EXCHANGE = "exchange"
    REPAIR = "repair"
    COMPLAINT = "complaint"


class CaseStatus(StrEnum):
    CASE_OPEN = "case_open"
    WAITING_INFO = "waiting_info"
    READY_TO_ACT = "ready_to_act"
    PENDING_CONFIRMATION = "pending_confirmation"
    PENDING_APPROVAL = "pending_approval"
    PROCESSING = "processing"
    PENDING_PROVIDER = "pending_provider"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    HANDOFF = "handoff"
    MANUAL_REQUIRED = "manual_required"
    STUCK = "stuck"
    CANCELLED = "cancelled"


class TransitionActor(StrEnum):
    # 不是装饰性字段——_SYSTEM_OWNED_TARGETS 依赖它做权限判定。
    MODEL = "model"
    SYSTEM = "system"
    PROVIDER = "provider"
    HUMAN_AGENT = "human_agent"
    HUMAN_USER = "human_user"


class TransitionRejection(StrEnum):
    ILLEGAL_TRANSITION = "illegal_transition"
    TERMINAL_CASE = "terminal_case"
    ACTOR_NOT_PERMITTED = "actor_not_permitted"
    STALE_STATE_VERSION = "stale_state_version"


# 空集合表示终态。WAITING_INFO -> WAITING_INFO 是唯一允许的自转移：
# 连续追问多个缺失字段时，每一轮都要留下一条 timeline 记录。
CASE_TRANSITIONS: Mapping[CaseStatus, frozenset[CaseStatus]] = MappingProxyType(
    {
        CaseStatus.CASE_OPEN: frozenset(
            {
                CaseStatus.WAITING_INFO,
                CaseStatus.READY_TO_ACT,
                CaseStatus.HANDOFF,
                CaseStatus.CANCELLED,
                CaseStatus.STUCK,
            }
        ),
        CaseStatus.WAITING_INFO: frozenset(
            {
                CaseStatus.WAITING_INFO,
                CaseStatus.READY_TO_ACT,
                CaseStatus.HANDOFF,
                CaseStatus.CANCELLED,
                CaseStatus.STUCK,
            }
        ),
        CaseStatus.READY_TO_ACT: frozenset(
            {
                CaseStatus.PENDING_CONFIRMATION,
                CaseStatus.PENDING_APPROVAL,
                CaseStatus.PROCESSING,
                CaseStatus.WAITING_INFO,
                CaseStatus.HANDOFF,
                CaseStatus.CANCELLED,
                CaseStatus.STUCK,
            }
        ),
        CaseStatus.PENDING_CONFIRMATION: frozenset(
            {
                CaseStatus.PROCESSING,
                CaseStatus.READY_TO_ACT,
                CaseStatus.HANDOFF,
                CaseStatus.CANCELLED,
                CaseStatus.STUCK,
            }
        ),
        CaseStatus.PENDING_APPROVAL: frozenset(
            {
                CaseStatus.PROCESSING,
                CaseStatus.FAILED,
                CaseStatus.MANUAL_REQUIRED,
                CaseStatus.HANDOFF,
                CaseStatus.CANCELLED,
                CaseStatus.STUCK,
            }
        ),
        CaseStatus.PROCESSING: frozenset(
            {
                CaseStatus.PENDING_PROVIDER,
                CaseStatus.COMPLETED,
                CaseStatus.FAILED,
                CaseStatus.UNKNOWN,
                CaseStatus.STUCK,
            }
        ),
        CaseStatus.PENDING_PROVIDER: frozenset(
            {
                CaseStatus.COMPLETED,
                CaseStatus.FAILED,
                CaseStatus.UNKNOWN,
                CaseStatus.STUCK,
            }
        ),
        # 超时未知：只能对账，不能重试。
        CaseStatus.UNKNOWN: frozenset(
            {
                CaseStatus.COMPLETED,
                CaseStatus.FAILED,
                CaseStatus.MANUAL_REQUIRED,
                CaseStatus.PENDING_PROVIDER,
            }
        ),
        CaseStatus.FAILED: frozenset(
            {
                CaseStatus.READY_TO_ACT,
                CaseStatus.MANUAL_REQUIRED,
                CaseStatus.HANDOFF,
            }
        ),
        CaseStatus.STUCK: frozenset({CaseStatus.MANUAL_REQUIRED, CaseStatus.HANDOFF}),
        CaseStatus.MANUAL_REQUIRED: frozenset(
            {CaseStatus.HANDOFF, CaseStatus.COMPLETED, CaseStatus.CANCELLED}
        ),
        CaseStatus.HANDOFF: frozenset(
            {CaseStatus.COMPLETED, CaseStatus.CANCELLED, CaseStatus.MANUAL_REQUIRED}
        ),
        CaseStatus.COMPLETED: frozenset(),
        CaseStatus.CANCELLED: frozenset(),
    }
)

# 只能由代码 / 供应商 / 人工驱动的目标状态，模型进不来。
# 这就是"终态必须回读数据库，不信回复文本"在状态机层面的落地。
_SYSTEM_OWNED_TARGETS: frozenset[CaseStatus] = frozenset(
    {
        CaseStatus.PROCESSING,
        CaseStatus.PENDING_PROVIDER,
        CaseStatus.COMPLETED,
        CaseStatus.FAILED,
        CaseStatus.UNKNOWN,
        CaseStatus.MANUAL_REQUIRED,
        CaseStatus.CANCELLED,
    }
)

_HUMAN_REQUIRED: frozenset[CaseStatus] = frozenset(
    {CaseStatus.STUCK, CaseStatus.MANUAL_REQUIRED, CaseStatus.HANDOFF}
)


@dataclass(frozen=True, slots=True)
class CaseTimelineEntry:
    from_status: CaseStatus
    to_status: CaseStatus
    actor: TransitionActor
    at: datetime
    note: str = ""


@dataclass(frozen=True, slots=True)
class AfterSalesCase:
    id: str
    goal_id: str
    tenant_id: str
    user_id: str
    order_id: str | None
    case_type: CaseType
    reason: str
    status: CaseStatus
    state_version: int
    created_at: datetime
    updated_at: datetime
    policy_id: str | None = None
    policy_version: str | None = None
    owner: str | None = None
    handoff_ticket_id: str | None = None
    timeline: tuple[CaseTimelineEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class TransitionOutcome:
    # 刻意不抛异常：拒绝原因要能原样进审计和用户可见的解释。
    ok: bool
    from_status: CaseStatus
    to_status: CaseStatus
    reason: str
    case: AfterSalesCase | None = None
    rejection: TransitionRejection | None = None


def is_terminal(status: CaseStatus) -> bool:
    return not CASE_TRANSITIONS[status]


def requires_human(status: CaseStatus) -> bool:
    return status in _HUMAN_REQUIRED


def apply_transition(
    case: AfterSalesCase,
    *,
    to_status: CaseStatus,
    actor: TransitionActor,
    at: datetime,
    expected_version: int,
    note: str = "",
) -> TransitionOutcome:
    # 检查顺序是刻意的：先版本、再终态、再拓扑、最后权限。版本冲突要优先报，
    # 因为那说明调用方读到的整个案件都是旧的，后面的判断都不可信。
    if case.state_version != expected_version:
        return TransitionOutcome(
            ok=False,
            from_status=case.status,
            to_status=to_status,
            rejection=TransitionRejection.STALE_STATE_VERSION,
            reason=(
                f"案件 {case.id} 的状态版本已变化：调用方持有 {expected_version}，"
                f"数据库为 {case.state_version}，请重新读取后再试"
            ),
        )

    if is_terminal(case.status):
        return TransitionOutcome(
            ok=False,
            from_status=case.status,
            to_status=to_status,
            rejection=TransitionRejection.TERMINAL_CASE,
            reason=(
                f"案件 {case.id} 已处于终态 {case.status.name}，不能再转移；"
                f"如需继续处理请新建案件"
            ),
        )

    if to_status not in CASE_TRANSITIONS[case.status]:
        return TransitionOutcome(
            ok=False,
            from_status=case.status,
            to_status=to_status,
            rejection=TransitionRejection.ILLEGAL_TRANSITION,
            reason=(
                f"不允许从 {case.status.name} 转移到 {to_status.name}；"
                f"合法目标为 {sorted(s.name for s in CASE_TRANSITIONS[case.status])}"
            ),
        )

    if actor is TransitionActor.MODEL and to_status in _SYSTEM_OWNED_TARGETS:
        return TransitionOutcome(
            ok=False,
            from_status=case.status,
            to_status=to_status,
            rejection=TransitionRejection.ACTOR_NOT_PERMITTED,
            reason=(
                f"{to_status.name} 只能由代码回读数据库后写入，模型不能直接宣布该状态"
            ),
        )

    entry = CaseTimelineEntry(
        from_status=case.status,
        to_status=to_status,
        actor=actor,
        at=at,
        note=note,
    )
    updated = replace(
        case,
        status=to_status,
        state_version=case.state_version + 1,
        updated_at=at,
        timeline=(*case.timeline, entry),
    )
    return TransitionOutcome(
        ok=True,
        from_status=case.status,
        to_status=to_status,
        reason=f"{case.status.name} -> {to_status.name}",
        case=updated,
    )
