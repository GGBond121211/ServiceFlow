"""Goal 归属判定的确定性测试。

对应计划里那句硬约束：**一个 Goal 不能被无声地改成另一个案件。**
用户说"刚才那个售后"时按 sessionId + goalId 恢复；换订单、换问题、
或原案件已完成，都必须开新 Goal 而不是改写旧的。
"""

from datetime import UTC, datetime

from serviceflow.domain.sessions import (
    AfterSalesGoal,
    GoalResolution,
    GoalStatus,
    missing_facts,
    resolve_goal,
)

AT = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)


def make_goal(
    goal_id: str,
    *,
    order_id: str | None,
    scene_code: str = "refund",
    status: GoalStatus = GoalStatus.ACTIVE,
    required: tuple[str, ...] = ("order_id", "requested_action"),
    known: dict[str, str] | None = None,
) -> AfterSalesGoal:
    return AfterSalesGoal(
        id=goal_id,
        session_id="SESSION-0001",
        tenant_id="TENANT-DEMO",
        user_id="USER-001",
        scene_code=scene_code,
        status=status,
        order_id=order_id,
        required_facts=required,
        known_facts=dict(known or {}),
        created_by="user",
        created_at=AT,
        updated_at=AT,
    )


# --- 新建 vs 继续 -----------------------------------------------------------


def test_first_message_in_a_session_opens_a_new_goal() -> None:
    outcome = resolve_goal(open_goals=(), order_id="ORDER-001", scene_code="refund")

    assert outcome.resolution is GoalResolution.NEW_GOAL
    assert outcome.goal is None
    assert outcome.reason


def test_follow_up_without_order_id_continues_the_only_open_goal() -> None:
    goal = make_goal("GOAL-1", order_id="ORDER-001")

    outcome = resolve_goal(open_goals=(goal,), order_id=None, scene_code="refund")

    assert outcome.resolution is GoalResolution.CONTINUE
    assert outcome.goal is goal


def test_follow_up_without_order_id_is_ambiguous_when_two_goals_are_open() -> None:
    """"刚才那个售后"在有两个未完成目标时不能猜——必须回问。"""
    a = make_goal("GOAL-1", order_id="ORDER-001")
    b = make_goal("GOAL-2", order_id="ORDER-002")

    outcome = resolve_goal(open_goals=(a, b), order_id=None, scene_code="refund")

    assert outcome.resolution is GoalResolution.AMBIGUOUS
    assert outcome.goal is None
    assert outcome.candidates == (a, b)


def test_matching_order_continues_that_goal_even_with_other_goals_open() -> None:
    a = make_goal("GOAL-1", order_id="ORDER-001")
    b = make_goal("GOAL-2", order_id="ORDER-002")

    outcome = resolve_goal(open_goals=(a, b), order_id="ORDER-002", scene_code="refund")

    assert outcome.resolution is GoalResolution.CONTINUE
    assert outcome.goal is b


def test_new_order_opens_a_new_goal() -> None:
    goal = make_goal("GOAL-1", order_id="ORDER-001")

    outcome = resolve_goal(open_goals=(goal,), order_id="ORDER-999", scene_code="refund")

    assert outcome.resolution is GoalResolution.NEW_GOAL
    assert outcome.goal is None


def test_same_order_different_scene_opens_a_new_goal() -> None:
    """同一订单从退款改成换货，是**新案件**，不是把旧 Goal 改掉。"""
    goal = make_goal("GOAL-1", order_id="ORDER-001", scene_code="refund")

    outcome = resolve_goal(open_goals=(goal,), order_id="ORDER-001", scene_code="exchange")

    assert outcome.resolution is GoalResolution.NEW_GOAL
    assert outcome.goal is None
    assert "scene" in outcome.reason


def test_completed_goal_is_never_continued() -> None:
    done = make_goal("GOAL-1", order_id="ORDER-001", status=GoalStatus.COMPLETED)

    outcome = resolve_goal(open_goals=(done,), order_id="ORDER-001", scene_code="refund")

    assert outcome.resolution is GoalResolution.NEW_GOAL


def test_abandoned_goal_is_never_continued() -> None:
    dropped = make_goal("GOAL-1", order_id="ORDER-001", status=GoalStatus.ABANDONED)

    outcome = resolve_goal(open_goals=(dropped,), order_id=None, scene_code="refund")

    assert outcome.resolution is GoalResolution.NEW_GOAL


def test_goal_without_order_yet_is_continued_when_order_arrives() -> None:
    """第一轮没给订单号，第二轮补上——这是继续同一个目标，不是新目标。"""
    goal = make_goal("GOAL-1", order_id=None, scene_code="refund")

    outcome = resolve_goal(open_goals=(goal,), order_id="ORDER-001", scene_code="refund")

    assert outcome.resolution is GoalResolution.CONTINUE
    assert outcome.goal is goal


def test_unspecified_scene_does_not_split_the_goal() -> None:
    """模型这一轮没识别出场景时不能因此开新目标。"""
    goal = make_goal("GOAL-1", order_id="ORDER-001", scene_code="refund")

    outcome = resolve_goal(open_goals=(goal,), order_id="ORDER-001", scene_code=None)

    assert outcome.resolution is GoalResolution.CONTINUE
    assert outcome.goal is goal


# --- 缺失事实 ---------------------------------------------------------------


def test_missing_facts_is_required_minus_known() -> None:
    goal = make_goal(
        "GOAL-1",
        order_id="ORDER-001",
        required=("order_id", "requested_action", "issue_type"),
        known={"order_id": "ORDER-001"},
    )

    assert missing_facts(goal) == ("requested_action", "issue_type")


def test_missing_facts_ignores_empty_values() -> None:
    """空字符串不算已知——否则模型填个空值就能骗过澄清逻辑。"""
    goal = make_goal(
        "GOAL-1",
        order_id="ORDER-001",
        required=("order_id", "requested_action"),
        known={"order_id": "ORDER-001", "requested_action": ""},
    )

    assert missing_facts(goal) == ("requested_action",)


def test_missing_facts_preserves_required_order() -> None:
    goal = make_goal(
        "GOAL-1",
        order_id=None,
        required=("order_id", "requested_action", "issue_type"),
        known={"requested_action": "refund"},
    )

    assert missing_facts(goal) == ("order_id", "issue_type")


def test_no_missing_facts_when_all_known() -> None:
    goal = make_goal(
        "GOAL-1",
        order_id="ORDER-001",
        required=("order_id",),
        known={"order_id": "ORDER-001"},
    )

    assert missing_facts(goal) == ()
