from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.domain.cases import (
    AfterSalesCase,
    CaseStatus,
    CaseTimelineEntry,
    CaseType,
    TransitionActor,
    TransitionOutcome,
    TransitionRejection,
    apply_transition,
)
from serviceflow.domain.models import (
    Approval,
    ApprovalStatus,
    Refund,
    RefundStatus,
    RequestedAction,
    Ticket,
    TicketKind,
    TicketStatus,
)
from serviceflow.domain.operations import (
    OPERATION_TRANSITIONS,
    ActionType,
    ErrorClass,
    Operation,
    OperationStatus,
    is_operation_terminal,
)
from serviceflow.infrastructure.database import ensure_utc
from serviceflow.infrastructure.tables import (
    AfterSalesCaseRow,
    ApprovalRow,
    CaseTimelineRow,
    OperationRow,
    RefundRow,
    TicketRow,
)

CaseEntity = Refund | Ticket | Approval


class CaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_refund(
        self,
        *,
        case_id: str,
        order_id: str,
        amount: Decimal,
        status: RefundStatus,
        created_at: datetime,
    ) -> Refund:
        row = RefundRow(
            id=case_id,
            order_id=order_id,
            amount=amount,
            status=status.value,
            created_at=created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return _refund_to_domain(row)

    async def create_ticket(
        self,
        *,
        case_id: str,
        order_id: str,
        kind: TicketKind,
        summary: str,
        created_at: datetime,
    ) -> Ticket:
        row = TicketRow(
            id=case_id,
            order_id=order_id,
            kind=kind.value,
            status=TicketStatus.OPEN.value,
            summary=summary,
            created_at=created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return _ticket_to_domain(row)

    async def create_approval(
        self,
        *,
        case_id: str,
        order_id: str,
        requested_action: RequestedAction,
        created_at: datetime,
    ) -> Approval:
        row = ApprovalRow(
            id=case_id,
            order_id=order_id,
            requested_action=requested_action.value,
            status=ApprovalStatus.PENDING.value,
            created_at=created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return _approval_to_domain(row)

    async def get(self, case_id: str) -> CaseEntity | None:
        refund = await self._session.get(RefundRow, case_id)
        if refund is not None:
            return _refund_to_domain(refund)
        ticket = await self._session.get(TicketRow, case_id)
        if ticket is not None:
            return _ticket_to_domain(ticket)
        approval = await self._session.get(ApprovalRow, case_id)
        if approval is not None:
            return _approval_to_domain(approval)
        return None

    async def get_approval(self, approval_id: str) -> Approval | None:
        row = await self._session.get(ApprovalRow, approval_id)
        if row is None:
            return None
        return _approval_to_domain(row)

    async def decide_pending_approval(
        self,
        approval_id: str,
        status: ApprovalStatus,
    ) -> Approval | None:
        result = await self._session.execute(
            update(ApprovalRow)
            .where(
                ApprovalRow.id == approval_id,
                ApprovalRow.status == ApprovalStatus.PENDING.value,
            )
            .values(status=status.value)
        )
        return await self.get_approval(approval_id) if result.rowcount == 1 else None


class AfterSalesCaseStore:
    """AfterSalesCase 的持久化，含乐观锁转移。

    与上面 `CaseRepository` 的关系：那个写的是**业务结果**（refunds / tickets /
    approvals 三张 V1 表），这个写的是**案件状态**。V1 的三张表一行不改。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        case_id: str,
        goal_id: str,
        tenant_id: str,
        user_id: str,
        order_id: str | None,
        case_type: CaseType,
        reason: str,
        at: datetime,
        policy_id: str | None = None,
        policy_version: str | None = None,
        owner: str | None = None,
    ) -> AfterSalesCase:
        row = AfterSalesCaseRow(
            id=case_id,
            goal_id=goal_id,
            tenant_id=tenant_id,
            user_id=user_id,
            order_id=order_id,
            case_type=case_type.value,
            reason=reason,
            status=CaseStatus.CASE_OPEN.value,
            state_version=1,
            policy_id=policy_id,
            policy_version=policy_version,
            owner=owner,
            created_at=at,
            updated_at=at,
        )
        self._session.add(row)
        await self._session.flush()
        return _case_to_domain(row, ())

    async def get(self, case_id: str) -> AfterSalesCase | None:
        row = await self._session.get(AfterSalesCaseRow, case_id)
        if row is None:
            return None
        timeline = await self._timeline(case_id)
        return _case_to_domain(row, timeline)

    async def transition(
        self,
        *,
        case_id: str,
        to_status: CaseStatus,
        actor: TransitionActor,
        expected_version: int,
        at: datetime,
        note: str = "",
    ) -> TransitionOutcome:
        """先用领域函数校验，再用带版本条件的 UPDATE 落库。

        两道锁不是重复：领域函数挡的是"这条转移不合法"，`WHERE state_version = ?`
        挡的是"我读到这条案件之后、写回之前，别人改过它"。只有后者能防并发。
        """
        current = await self.get(case_id)
        if current is None:
            return TransitionOutcome(
                ok=False,
                from_status=to_status,
                to_status=to_status,
                rejection=TransitionRejection.ILLEGAL_TRANSITION,
                reason=f"案件 {case_id} 不存在",
            )

        outcome = apply_transition(
            current,
            to_status=to_status,
            actor=actor,
            at=at,
            expected_version=expected_version,
            note=note,
        )
        if not outcome.ok or outcome.case is None:
            return outcome

        result = await self._session.execute(
            update(AfterSalesCaseRow)
            .where(
                AfterSalesCaseRow.id == case_id,
                AfterSalesCaseRow.state_version == expected_version,
            )
            .values(
                status=to_status.value,
                state_version=expected_version + 1,
                updated_at=at,
            )
        )
        if result.rowcount == 0:
            # 领域校验通过但 UPDATE 没命中：说明这一瞬间有人抢先改了。
            latest = await self.get(case_id)
            actual = latest.state_version if latest else "unknown"
            return TransitionOutcome(
                ok=False,
                from_status=current.status,
                to_status=to_status,
                rejection=TransitionRejection.STALE_STATE_VERSION,
                reason=(
                    f"案件 {case_id} 在本次写入前被并发修改：调用方持有 "
                    f"{expected_version}，数据库为 {actual}，请重新读取后再试"
                ),
            )

        self._session.add(
            CaseTimelineRow(
                case_id=case_id,
                from_status=current.status.value,
                to_status=to_status.value,
                actor=actor.value,
                at=at,
                note=note,
            )
        )
        await self._session.flush()
        return outcome

    async def _timeline(self, case_id: str) -> tuple[CaseTimelineEntry, ...]:
        rows = await self._session.scalars(
            select(CaseTimelineRow)
            .where(CaseTimelineRow.case_id == case_id)
            .order_by(CaseTimelineRow.seq)
        )
        return tuple(
            CaseTimelineEntry(
                from_status=CaseStatus(row.from_status),
                to_status=CaseStatus(row.to_status),
                actor=TransitionActor(row.actor),
                at=ensure_utc(row.at),
                note=row.note,
            )
            for row in rows
        )


class OperationStore:
    """Operation 的持久化。幂等靠 `action_id` 的唯一约束兜底。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, operation_id: str) -> Operation | None:
        row = await self._session.get(OperationRow, operation_id)
        if row is None:
            return None
        return _operation_to_domain(row)

    async def get_by_action_id(self, action_id: str) -> Operation | None:
        row = await self._session.scalar(
            select(OperationRow).where(OperationRow.action_id == action_id)
        )
        if row is None:
            return None
        return _operation_to_domain(row)

    async def count_for_case(self, case_id: str) -> int:
        count = await self._session.scalar(
            select(func.count()).select_from(OperationRow).where(OperationRow.case_id == case_id)
        )
        return int(count or 0)

    async def list_for_case(self, case_id: str) -> tuple[Operation, ...]:
        rows = await self._session.scalars(
            select(OperationRow)
            .where(OperationRow.case_id == case_id)
            .order_by(OperationRow.requested_at, OperationRow.id)
        )
        return tuple(_operation_to_domain(row) for row in rows)

    async def insert(
        self,
        *,
        operation_id: str,
        case_id: str,
        action_type: ActionType,
        action_id: str,
        fingerprint: str,
        status: OperationStatus,
        at: datetime,
        trace_id: str | None = None,
    ) -> Operation | None:
        """插入一条新操作。`action_id` 撞唯一约束时返回 `None`。

        返回 None 而不是抛异常：并发下"别人先插进去了"是**预期路径**，
        调用方应当去读那一条并重放，不是报错。
        """
        row = OperationRow(
            id=operation_id,
            case_id=case_id,
            action_type=action_type.value,
            action_id=action_id,
            request_fingerprint=fingerprint,
            status=status.value,
            state_version=1,
            attempt=1,
            error_class=ErrorClass.NONE.value,
            requested_at=at,
            started_at=at if status is OperationStatus.DISPATCHED else None,
            trace_id=trace_id,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            return None
        return _operation_to_domain(row)

    async def begin_retry(self, operation_id: str, *, at: datetime) -> Operation:
        row = await self._session.scalar(
            select(OperationRow)
            .where(OperationRow.id == operation_id)
            .with_for_update()
        )
        if row is None:
            raise LookupError("operation_not_found")
        row.status = OperationStatus.DISPATCHED.value
        row.attempt = row.attempt + 1
        row.state_version = row.state_version + 1
        row.started_at = at
        row.finished_at = None
        row.error_class = ErrorClass.NONE.value
        row.result_code = None
        await self._session.flush()
        return _operation_to_domain(row)

    async def finish(
        self,
        operation_id: str,
        *,
        status: OperationStatus,
        at: datetime,
        result_code: str | None = None,
        error_class: ErrorClass = ErrorClass.NONE,
        provider_ref: str | None = None,
    ) -> Operation:
        row = await self._session.scalar(
            select(OperationRow)
            .where(OperationRow.id == operation_id)
            .with_for_update()
        )
        if row is None:
            raise LookupError("operation_not_found")
        current = OperationStatus(row.status)
        if status is current and is_operation_terminal(current):
            return _operation_to_domain(row)
        if status not in OPERATION_TRANSITIONS[current]:
            raise ValueError(
                f"操作 {operation_id} 不允许从 {current.name} 转到 {status.name}；"
                f"合法目标为 {sorted(s.name for s in OPERATION_TRANSITIONS[current])}"
            )
        row.status = status.value
        row.state_version = row.state_version + 1
        row.finished_at = (
            at
            if status
            in {
                OperationStatus.SUCCEEDED,
                OperationStatus.FAILED,
                OperationStatus.CANCELLED,
                OperationStatus.MANUAL_REQUIRED,
            }
            else None
        )
        row.result_code = result_code
        row.error_class = error_class.value
        if provider_ref is not None:
            row.provider_ref = provider_ref
        await self._session.flush()
        return _operation_to_domain(row)


def _case_to_domain(
    row: AfterSalesCaseRow,
    timeline: tuple[CaseTimelineEntry, ...],
) -> AfterSalesCase:
    return AfterSalesCase(
        id=row.id,
        goal_id=row.goal_id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        order_id=row.order_id,
        case_type=CaseType(row.case_type),
        reason=row.reason,
        status=CaseStatus(row.status),
        state_version=row.state_version,
        policy_id=row.policy_id,
        policy_version=row.policy_version,
        owner=row.owner,
        handoff_ticket_id=row.handoff_ticket_id,
        created_at=ensure_utc(row.created_at),
        updated_at=ensure_utc(row.updated_at),
        timeline=timeline,
    )


def _operation_to_domain(row: OperationRow) -> Operation:
    return Operation(
        id=row.id,
        case_id=row.case_id,
        action_type=ActionType(row.action_type),
        action_id=row.action_id,
        request_fingerprint=row.request_fingerprint,
        status=OperationStatus(row.status),
        state_version=row.state_version,
        attempt=row.attempt,
        error_class=ErrorClass(row.error_class),
        result_code=row.result_code,
        provider_ref=row.provider_ref,
        trace_id=row.trace_id,
        requested_at=ensure_utc(row.requested_at),
        confirmed_at=ensure_utc(row.confirmed_at),
        approved_at=ensure_utc(row.approved_at),
        started_at=ensure_utc(row.started_at),
        finished_at=ensure_utc(row.finished_at),
    )


def _refund_to_domain(row: RefundRow) -> Refund:
    return Refund(
        id=row.id,
        order_id=row.order_id,
        amount=row.amount,
        status=RefundStatus(row.status),
        created_at=_with_utc(row.created_at),
    )


def _ticket_to_domain(row: TicketRow) -> Ticket:
    return Ticket(
        id=row.id,
        order_id=row.order_id,
        kind=TicketKind(row.kind),
        status=TicketStatus(row.status),
        summary=row.summary,
        created_at=_with_utc(row.created_at),
    )


def _approval_to_domain(row: ApprovalRow) -> Approval:
    return Approval(
        id=row.id,
        order_id=row.order_id,
        requested_action=RequestedAction(row.requested_action),
        status=ApprovalStatus(row.status),
        created_at=_with_utc(row.created_at),
    )


def _with_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)
