"""AfterSalesCase 状态机的确定性测试。

这里只测纯函数，不碰数据库。状态机是 Step 2 的核心不变量所在：
模型可以推动对话状态，但**不能**宣布业务终态——那必须由代码回读数据库后写入。
"""

from datetime import UTC, datetime

import pytest

from serviceflow.domain.cases import (
    CASE_TRANSITIONS,
    AfterSalesCase,
    CaseStatus,
    CaseType,
    TransitionActor,
    TransitionRejection,
    apply_transition,
    is_terminal,
    requires_human,
)

AT = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)


def make_case(status: CaseStatus = CaseStatus.CASE_OPEN, version: int = 1) -> AfterSalesCase:
    return AfterSalesCase(
        id="CASE-0001",
        goal_id="GOAL-0001",
        tenant_id="TENANT-DEMO",
        user_id="USER-001",
        order_id="ORDER-001",
        case_type=CaseType.REFUND,
        reason="收到的商品有质量问题",
        status=status,
        state_version=version,
        policy_id="POL-REFUND-01",
        policy_version="v1",
        created_at=AT,
        updated_at=AT,
    )


# --- 合法路径 ---------------------------------------------------------------


def test_happy_path_chain_is_legal() -> None:
    case = make_case()
    chain = [
        (CaseStatus.WAITING_INFO, TransitionActor.MODEL),
        (CaseStatus.READY_TO_ACT, TransitionActor.MODEL),
        (CaseStatus.PENDING_CONFIRMATION, TransitionActor.MODEL),
        (CaseStatus.PROCESSING, TransitionActor.SYSTEM),
        (CaseStatus.PENDING_PROVIDER, TransitionActor.SYSTEM),
        (CaseStatus.COMPLETED, TransitionActor.SYSTEM),
    ]
    for target, actor in chain:
        outcome = apply_transition(
            case,
            to_status=target,
            actor=actor,
            at=AT,
            note="test",
            expected_version=case.state_version,
        )
        assert outcome.ok is True, f"{case.status} -> {target} 应当合法"
        assert outcome.case is not None
        case = outcome.case

    assert case.status is CaseStatus.COMPLETED
    assert case.state_version == 7
    assert len(case.timeline) == 6
    assert [entry.to_status for entry in case.timeline] == [target for target, _ in chain]


def test_transition_bumps_version_and_appends_timeline() -> None:
    case = make_case()
    outcome = apply_transition(
        case,
        to_status=CaseStatus.WAITING_INFO,
        actor=TransitionActor.MODEL,
        at=AT,
        note="缺订单号",
        expected_version=1,
    )

    assert outcome.ok is True
    assert outcome.case is not None
    assert outcome.case.state_version == 2
    assert outcome.case.timeline[-1].from_status is CaseStatus.CASE_OPEN
    assert outcome.case.timeline[-1].to_status is CaseStatus.WAITING_INFO
    assert outcome.case.timeline[-1].actor is TransitionActor.MODEL
    assert outcome.case.timeline[-1].note == "缺订单号"
    # 原对象不可变，未被就地修改
    assert case.state_version == 1
    assert case.timeline == ()


# --- 非法路径 ---------------------------------------------------------------


def test_illegal_transition_is_rejected_without_mutation() -> None:
    case = make_case(CaseStatus.CASE_OPEN)

    outcome = apply_transition(
        case,
        to_status=CaseStatus.COMPLETED,
        actor=TransitionActor.SYSTEM,
        at=AT,
        expected_version=1,
    )

    assert outcome.ok is False
    assert outcome.case is None
    assert outcome.rejection is TransitionRejection.ILLEGAL_TRANSITION
    assert "CASE_OPEN" in outcome.reason
    assert case.status is CaseStatus.CASE_OPEN


def test_completed_case_is_terminal() -> None:
    case = make_case(CaseStatus.COMPLETED)
    assert is_terminal(CaseStatus.COMPLETED) is True
    assert CASE_TRANSITIONS[CaseStatus.COMPLETED] == frozenset()

    outcome = apply_transition(
        case,
        to_status=CaseStatus.READY_TO_ACT,
        actor=TransitionActor.HUMAN_AGENT,
        at=AT,
        expected_version=1,
    )

    assert outcome.ok is False
    assert outcome.rejection is TransitionRejection.TERMINAL_CASE


def test_unknown_cannot_go_straight_back_to_ready_to_act() -> None:
    """UNKNOWN 表示"不知道副作用有没有发生"，直接重试等于可能重复扣款。

    只允许先 reconcile 到 COMPLETED / FAILED / MANUAL_REQUIRED / PENDING_PROVIDER。
    """
    case = make_case(CaseStatus.UNKNOWN)

    outcome = apply_transition(
        case,
        to_status=CaseStatus.READY_TO_ACT,
        actor=TransitionActor.SYSTEM,
        at=AT,
        expected_version=1,
    )

    assert outcome.ok is False
    assert outcome.rejection is TransitionRejection.ILLEGAL_TRANSITION
    assert CaseStatus.READY_TO_ACT not in CASE_TRANSITIONS[CaseStatus.UNKNOWN]
    assert CASE_TRANSITIONS[CaseStatus.UNKNOWN] == frozenset(
        {
            CaseStatus.COMPLETED,
            CaseStatus.FAILED,
            CaseStatus.MANUAL_REQUIRED,
            CaseStatus.PENDING_PROVIDER,
        }
    )


def test_stale_state_version_is_rejected() -> None:
    case = make_case(CaseStatus.CASE_OPEN, version=5)

    outcome = apply_transition(
        case,
        to_status=CaseStatus.WAITING_INFO,
        actor=TransitionActor.MODEL,
        at=AT,
        expected_version=4,
    )

    assert outcome.ok is False
    assert outcome.rejection is TransitionRejection.STALE_STATE_VERSION
    assert "4" in outcome.reason and "5" in outcome.reason


# --- 模型权限边界（Step 2 的安全核心）--------------------------------------


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (CaseStatus.PROCESSING, CaseStatus.COMPLETED),
        (CaseStatus.PROCESSING, CaseStatus.FAILED),
        (CaseStatus.PROCESSING, CaseStatus.UNKNOWN),
        (CaseStatus.PENDING_CONFIRMATION, CaseStatus.PROCESSING),
        (CaseStatus.PENDING_PROVIDER, CaseStatus.COMPLETED),
    ],
)
def test_model_cannot_declare_business_outcome(
    from_status: CaseStatus, to_status: CaseStatus
) -> None:
    """模型不得自己宣布"办好了"。这些状态只能由代码在回读数据库后写入。"""
    case = make_case(from_status)

    rejected = apply_transition(
        case,
        to_status=to_status,
        actor=TransitionActor.MODEL,
        at=AT,
        expected_version=1,
    )
    assert rejected.ok is False
    assert rejected.rejection is TransitionRejection.ACTOR_NOT_PERMITTED

    allowed = apply_transition(
        case,
        to_status=to_status,
        actor=TransitionActor.SYSTEM,
        at=AT,
        expected_version=1,
    )
    assert allowed.ok is True, "同一条转移由 SYSTEM 驱动必须合法，否则测的不是权限而是拓扑"


def test_model_cannot_bypass_pending_approval() -> None:
    case = make_case(CaseStatus.PENDING_APPROVAL)

    outcome = apply_transition(
        case,
        to_status=CaseStatus.PROCESSING,
        actor=TransitionActor.MODEL,
        at=AT,
        expected_version=1,
    )

    assert outcome.ok is False
    assert outcome.rejection is TransitionRejection.ACTOR_NOT_PERMITTED


def test_model_may_still_steer_the_conversation() -> None:
    """反向确认：模型不是什么都不能做，否则 2.0 的"模型自主"就没了。"""
    case = make_case(CaseStatus.READY_TO_ACT)
    for target in (
        CaseStatus.WAITING_INFO,
        CaseStatus.PENDING_CONFIRMATION,
        CaseStatus.PENDING_APPROVAL,
        CaseStatus.HANDOFF,
        CaseStatus.STUCK,
    ):
        outcome = apply_transition(
            case,
            to_status=target,
            actor=TransitionActor.MODEL,
            at=AT,
            expected_version=1,
        )
        assert outcome.ok is True, f"模型应当可以把案件推到 {target}"


# --- 表本身的完备性 ---------------------------------------------------------


def test_every_status_has_an_entry_in_the_transition_table() -> None:
    assert set(CASE_TRANSITIONS) == set(CaseStatus)


def test_no_transition_points_outside_the_enum() -> None:
    for source, targets in CASE_TRANSITIONS.items():
        for target in targets:
            assert isinstance(target, CaseStatus), f"{source} -> {target!r} 不是合法状态"
            assert target is not source or source is CaseStatus.WAITING_INFO, (
                f"{source} 不应允许自转移"
            )


def test_terminal_statuses_have_no_outgoing_edges() -> None:
    for status in CaseStatus:
        if is_terminal(status):
            assert CASE_TRANSITIONS[status] == frozenset(), f"{status} 被标为终态却仍有出边"


def test_stuck_only_escalates_to_humans() -> None:
    assert CASE_TRANSITIONS[CaseStatus.STUCK] == frozenset(
        {CaseStatus.MANUAL_REQUIRED, CaseStatus.HANDOFF}
    )
    assert requires_human(CaseStatus.STUCK) is True
    assert requires_human(CaseStatus.MANUAL_REQUIRED) is True
    assert requires_human(CaseStatus.HANDOFF) is True
    assert requires_human(CaseStatus.READY_TO_ACT) is False
