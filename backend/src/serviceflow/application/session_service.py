"""SessionService：Session / Goal / Case / Operation 的编排层，唯一有副作用的入口。

业务规则来自 policies.py，状态判定来自 cases.apply_transition，
幂等判定来自 operations.classify_replay——本层只负责落库、审计和并发复查。
事务边界见 experiments/DECISIONS.md S2-12。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from serviceflow.domain.cases import (
    AfterSalesCase,
    CaseStatus,
    CaseType,
    TransitionActor,
    TransitionOutcome,
)
from serviceflow.domain.operations import (
    ActionType,
    ErrorClass,
    Operation,
    OperationStatus,
    ReplayVerdict,
    classify_replay,
    request_fingerprint,
)
from serviceflow.domain.policies import required_facts_for
from serviceflow.domain.sessions import (
    AfterSalesGoal,
    Channel,
    ConversationSession,
    GoalResolutionOutcome,
    GoalStatus,
    missing_facts,
    resolve_goal,
)
from serviceflow.infrastructure.case_repository import AfterSalesCaseStore, OperationStore
from serviceflow.infrastructure.event_log import EventLog
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.session_repository import GoalStore, SessionStore


@dataclass(frozen=True, slots=True)
class OperationBegin:
    # 调用方只看 may_execute。自己去 if verdict 等于每个调用点重推一遍幂等语义，
    # 漏一个就是重复扣款。
    verdict: ReplayVerdict
    operation: Operation
    reason: str

    @property
    def may_execute(self) -> bool:
        return self.verdict.permits_execution


class SessionService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # --- 会话 ---------------------------------------------------------------

    async def start_session(
        self,
        *,
        tenant_id: str,
        user_id: str,
        channel: Channel,
        session_id: str | None = None,
    ) -> ConversationSession:
        now = _now()
        resolved_id = session_id or _new_id("SESSION")
        async with self._session_factory() as db:
            session = await SessionStore(db).create(
                session_id=resolved_id,
                tenant_id=tenant_id,
                user_id=user_id,
                channel=channel,
                at=now,
            )
            await EventLog(db).append(
                event_type="session_started",
                tenant_id=tenant_id,
                actor="system",
                session_id=session.id,
                payload={"channel": channel.value, "user_id": user_id},
                at=now,
            )
            await db.commit()
        return session

    async def load_session(self, session_id: str) -> ConversationSession | None:
        async with self._session_factory() as db:
            return await SessionStore(db).get(session_id)

    async def touch_session(self, session_id: str) -> ConversationSession:
        async with self._session_factory() as db:
            session = await SessionStore(db).touch(session_id, at=_now())
            await db.commit()
        return session

    # --- 目标 ---------------------------------------------------------------

    async def locate_goal(
        self,
        *,
        session_id: str,
        order_id: str | None,
        scene_code: str | None,
    ) -> GoalResolutionOutcome:
        # 只读不创建。判定全在 domain/sessions.resolve_goal，本方法只取数据喂它,
        # 这样"该不该开新目标"能脱离数据库单测。
        async with self._session_factory() as db:
            open_goals = await GoalStore(db).open_goals(session_id)
        return resolve_goal(open_goals=open_goals, order_id=order_id, scene_code=scene_code)

    async def open_goal(
        self,
        *,
        session_id: str,
        order_id: str | None,
        scene_code: str | None,
        created_by: str,
        required_facts: tuple[str, ...] | None = None,
    ) -> AfterSalesGoal:
        now = _now()
        async with self._session_factory() as db:
            session = await SessionStore(db).get(session_id)
            if session is None:
                raise LookupError("session_not_found")
            goal = await GoalStore(db).create(
                goal_id=_new_id("GOAL"),
                session_id=session_id,
                tenant_id=session.tenant_id,
                user_id=session.user_id,
                scene_code=scene_code,
                order_id=order_id,
                required_facts=required_facts or required_facts_for(scene_code),
                created_by=created_by,
                at=now,
            )
            await SessionStore(db).touch(session_id, at=now)
            await EventLog(db).append(
                event_type="goal_opened",
                tenant_id=session.tenant_id,
                actor=created_by,
                session_id=session_id,
                goal_id=goal.id,
                payload={"scene_code": scene_code, "order_id": order_id},
                at=now,
            )
            await db.commit()
        return goal

    async def load_goal(self, goal_id: str) -> AfterSalesGoal | None:
        async with self._session_factory() as db:
            return await GoalStore(db).get(goal_id)

    async def missing_facts_for(self, goal_id: str) -> tuple[str, ...]:
        goal = await self.load_goal(goal_id)
        if goal is None:
            raise LookupError("goal_not_found")
        return missing_facts(goal)

    async def record_facts(
        self,
        goal_id: str,
        facts: Mapping[str, str],
    ) -> AfterSalesGoal:
        # 只接受业务事实（订单号、动作、问题类型），不接受模型推理过程。
        now = _now()
        async with self._session_factory() as db:
            goal = await GoalStore(db).record_facts(goal_id, dict(facts), at=now)
            await EventLog(db).append(
                event_type="goal_facts_recorded",
                tenant_id=goal.tenant_id,
                actor="model",
                session_id=goal.session_id,
                goal_id=goal.id,
                payload={"recorded": sorted(facts), "still_missing": list(missing_facts(goal))},
                at=now,
            )
            await db.commit()
        return goal

    async def complete_goal(self, goal_id: str) -> AfterSalesGoal:
        return await self._set_goal_status(goal_id, GoalStatus.COMPLETED)

    async def _set_goal_status(self, goal_id: str, status: GoalStatus) -> AfterSalesGoal:
        now = _now()
        async with self._session_factory() as db:
            goal = await GoalStore(db).set_status(goal_id, status, at=now)
            await EventLog(db).append(
                event_type="goal_status_changed",
                tenant_id=goal.tenant_id,
                actor="system",
                session_id=goal.session_id,
                goal_id=goal.id,
                case_id=goal.case_id,
                payload={"status": status.value},
                at=now,
            )
            await db.commit()
        return goal

    # --- 案件 ---------------------------------------------------------------

    async def open_case(
        self,
        *,
        goal_id: str,
        order_id: str | None,
        case_type: CaseType,
        reason: str,
        policy_id: str | None = None,
        policy_version: str | None = None,
        owner: str | None = None,
    ) -> AfterSalesCase:
        now = _now()
        async with self._session_factory() as db:
            goal = await GoalStore(db).get(goal_id)
            if goal is None:
                raise LookupError("goal_not_found")
            case = await AfterSalesCaseStore(db).create(
                case_id=_new_id("CASE"),
                goal_id=goal_id,
                tenant_id=goal.tenant_id,
                user_id=goal.user_id,
                order_id=order_id,
                case_type=case_type,
                reason=reason,
                at=now,
                policy_id=policy_id,
                policy_version=policy_version,
                owner=owner,
            )
            # 一个 Goal 只能绑一个案件；改绑会在这里抛错。
            await GoalStore(db).attach_case(goal_id, case.id, at=now)
            await EventLog(db).append(
                event_type="case_opened",
                tenant_id=goal.tenant_id,
                actor="system",
                session_id=goal.session_id,
                goal_id=goal_id,
                case_id=case.id,
                payload={
                    "case_type": case_type.value,
                    "order_id": order_id,
                    "policy_id": policy_id,
                    "policy_version": policy_version,
                },
                at=now,
            )
            await db.commit()
        return case

    async def load_case(self, case_id: str) -> AfterSalesCase | None:
        async with self._session_factory() as db:
            return await AfterSalesCaseStore(db).get(case_id)

    async def transition_case(
        self,
        *,
        case_id: str,
        to_status: CaseStatus,
        actor: TransitionActor,
        expected_version: int,
        note: str = "",
    ) -> TransitionOutcome:
        # 被拒也要写审计："谁试图非法推进状态"本身就是要留痕的信息。
        now = _now()
        async with self._session_factory() as db:
            store = AfterSalesCaseStore(db)
            outcome = await store.transition(
                case_id=case_id,
                to_status=to_status,
                actor=actor,
                expected_version=expected_version,
                at=now,
                note=note,
            )
            case = outcome.case or await store.get(case_id)
            tenant_id = case.tenant_id if case else "unknown"
            event_type = "case_transitioned" if outcome.ok else "case_transition_rejected"
            payload: dict[str, Any] = {
                "from": outcome.from_status.value,
                "to": to_status.value,
                "actor": actor.value,
                "note": note,
            }
            if not outcome.ok:
                payload["rejection"] = (
                    outcome.rejection.value if outcome.rejection else "unknown"
                )
                payload["reason"] = outcome.reason
            await EventLog(db).append(
                event_type=event_type,
                tenant_id=tenant_id,
                actor=actor.value,
                case_id=case_id,
                goal_id=case.goal_id if case else None,
                payload=payload,
                at=now,
            )
            await db.commit()
        return outcome

    # --- 操作 ---------------------------------------------------------------

    async def begin_operation(
        self,
        *,
        case_id: str,
        action_type: ActionType,
        action_id: str,
        payload: Mapping[str, Any],
        requires_confirmation: bool = False,
        trace_id: str | None = None,
    ) -> OperationBegin:
        # 并发路径：两个协程可能同时读到 existing is None 并都判 FIRST_ATTEMPT。
        # action_id 的唯一约束让其中一个 INSERT 失败、insert() 返回 None，
        # 此时重读重判变成 IN_FLIGHT。详见 DECISIONS.md S2-7。
        now = _now()
        fingerprint = request_fingerprint(
            action_type=action_type, case_id=case_id, payload=payload
        )
        initial = (
            OperationStatus.CONFIRMATION_REQUIRED
            if requires_confirmation
            else OperationStatus.DISPATCHED
        )
        async with self._session_factory() as db:
            store = OperationStore(db)
            existing = await store.get_by_action_id(action_id)
            verdict = classify_replay(existing=existing, fingerprint=fingerprint)

            if verdict is ReplayVerdict.FIRST_ATTEMPT:
                created = await store.insert(
                    operation_id=_new_id("OP"),
                    case_id=case_id,
                    action_type=action_type,
                    action_id=action_id,
                    fingerprint=fingerprint,
                    status=initial,
                    at=now,
                    trace_id=trace_id,
                )
                if created is None:
                    # 并发插入撞了唯一键：重读并重判。
                    existing = await store.get_by_action_id(action_id)
                    if existing is None:  # pragma: no cover - 唯一键失败但读不到，不该发生
                        raise RuntimeError("operation_insert_conflict_without_row")
                    verdict = classify_replay(existing=existing, fingerprint=fingerprint)
                    operation = existing
                else:
                    operation = created
                    await self._log_operation_event(
                        db,
                        event_type="operation_requested",
                        operation=operation,
                        payload={
                            "action_type": action_type.value,
                            "fingerprint": fingerprint,
                            "requires_confirmation": requires_confirmation,
                        },
                        trace_id=trace_id,
                        at=now,
                    )
            elif verdict is ReplayVerdict.RETRYABLE:
                assert existing is not None
                operation = await store.begin_retry(existing.id, at=now)
                await self._log_operation_event(
                    db,
                    event_type="operation_retried",
                    operation=operation,
                    payload={"attempt": operation.attempt},
                    trace_id=trace_id,
                    at=now,
                )
            else:
                assert existing is not None
                operation = existing
                await self._log_operation_event(
                    db,
                    event_type="operation_replayed",
                    operation=operation,
                    payload={"verdict": verdict.value},
                    trace_id=trace_id,
                    at=now,
                )

            await db.commit()

        return OperationBegin(
            verdict=verdict,
            operation=operation,
            reason=_verdict_reason(verdict, action_id),
        )

    async def finish_operation(
        self,
        *,
        operation_id: str,
        status: OperationStatus,
        result_code: str | None = None,
        error_class: ErrorClass = ErrorClass.NONE,
        provider_ref: str | None = None,
    ) -> Operation:
        now = _now()
        async with self._session_factory() as db:
            operation = await OperationStore(db).finish(
                operation_id,
                status=status,
                at=now,
                result_code=result_code,
                error_class=error_class,
                provider_ref=provider_ref,
            )
            await self._log_operation_event(
                db,
                event_type="operation_finished",
                operation=operation,
                payload={
                    "status": status.value,
                    "result_code": result_code,
                    "error_class": error_class.value,
                    "provider_ref": provider_ref,
                    "attempt": operation.attempt,
                },
                trace_id=operation.trace_id,
                at=now,
            )
            await db.commit()
        return operation

    async def count_operations(self, case_id: str) -> int:
        async with self._session_factory() as db:
            return await OperationStore(db).count_for_case(case_id)

    # --- 终态 ---------------------------------------------------------------

    async def final_state(self, case_id: str) -> dict[str, Any]:
        # 不接受任何模型输出作为输入——CLAUDE.md §3「终态必须回读数据库」。
        async with self._session_factory() as db:
            case = await AfterSalesCaseStore(db).get(case_id)
            if case is None:
                raise LookupError("case_not_found")
            operations = await OperationStore(db).list_for_case(case_id)
            order = None
            if case.order_id:
                order = await OrderRepository(db).get(case.order_id)
        return {
            "case_id": case.id,
            "case_status": case.status.value,
            "state_version": case.state_version,
            "order_id": case.order_id,
            "order_status": order.status.value if order else None,
            "operations": [
                {
                    "operation_id": operation.id,
                    "action_type": operation.action_type.value,
                    "status": operation.status.value,
                    "result_code": operation.result_code,
                    "attempt": operation.attempt,
                }
                for operation in operations
            ],
        }

    # --- 内部 ---------------------------------------------------------------

    async def _log_operation_event(
        self,
        db: AsyncSession,
        *,
        event_type: str,
        operation: Operation,
        payload: Mapping[str, Any],
        trace_id: str | None,
        at: datetime,
    ) -> None:
        case = await AfterSalesCaseStore(db).get(operation.case_id)
        await EventLog(db).append(
            event_type=event_type,
            tenant_id=case.tenant_id if case else "unknown",
            actor="system",
            goal_id=case.goal_id if case else None,
            case_id=operation.case_id,
            operation_id=operation.id,
            trace_id=trace_id,
            payload=dict(payload),
            at=at,
        )


def _verdict_reason(verdict: ReplayVerdict, action_id: str) -> str:
    if verdict is ReplayVerdict.FIRST_ATTEMPT:
        return f"actionId {action_id} 首次登记，可以执行"
    if verdict is ReplayVerdict.RETRYABLE:
        return f"actionId {action_id} 上一次失败，允许重试"
    if verdict is ReplayVerdict.ALREADY_SUCCEEDED:
        return f"actionId {action_id} 已成功执行过，直接返回原结果，不再产生副作用"
    if verdict is ReplayVerdict.IN_FLIGHT:
        return f"actionId {action_id} 正在执行中，不能并发再发一次"
    if verdict is ReplayVerdict.NEEDS_RECONCILE:
        return (
            f"actionId {action_id} 上一次超时，副作用是否发生未知；"
            f"必须先对账，不能直接重试"
        )
    return (
        f"actionId {action_id} 已被用过，但本次请求参数与首次不一致；"
        f"拒绝执行（同一幂等键不允许换参数）"
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12].upper()}"
