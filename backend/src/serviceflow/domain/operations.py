"""Operation：一次有副作用的操作，及其幂等判定。纯函数，无 I/O。

refunds / tickets / approvals 三张 V1 表是业务结果，Operation 是执行过程。
幂等判定保持为纯函数，便于重复测试。
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType
from typing import Any


class ActionType(StrEnum):
    # QUERY_ORDER 也在这里是因为它需要被审计，只是 has_side_effect 为假。
    QUERY_ORDER = "query_order"
    CANCEL_ORDER = "cancel_order"
    REFUND = "refund"
    CREATE_EXCHANGE_TICKET = "create_exchange_ticket"
    CREATE_SUPPORT_TICKET = "create_support_ticket"
    CREATE_APPROVAL = "create_approval"
    DECIDE_APPROVAL = "decide_approval"
    HANDOFF = "handoff"

    @property
    def has_side_effect(self) -> bool:
        return self is not ActionType.QUERY_ORDER


class OperationStatus(StrEnum):
    CREATED = "created"
    CONFIRMATION_REQUIRED = "confirmation_required"
    APPROVAL_REQUIRED = "approval_required"
    DISPATCHED = "dispatched"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"
    MANUAL_REQUIRED = "manual_required"


class ErrorClass(StrEnum):
    # 低基数标签，可进 Metrics（补充 C）。
    NONE = "none"
    VALIDATION = "validation"
    POLICY_REJECTED = "policy_rejected"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    INTERNAL = "internal"


class ReplayVerdict(StrEnum):
    # permits_execution 是关键：调用方只问"我能执行吗"，不自己 if 一遍状态。
    FIRST_ATTEMPT = "first_attempt"
    ALREADY_SUCCEEDED = "already_succeeded"
    IN_FLIGHT = "in_flight"
    RETRYABLE = "retryable"
    NEEDS_RECONCILE = "needs_reconcile"
    FINGERPRINT_MISMATCH = "fingerprint_mismatch"

    @property
    def permits_execution(self) -> bool:
        return self in (ReplayVerdict.FIRST_ATTEMPT, ReplayVerdict.RETRYABLE)


OPERATION_TRANSITIONS: Mapping[OperationStatus, frozenset[OperationStatus]] = MappingProxyType(
    {
        OperationStatus.CREATED: frozenset(
            {
                OperationStatus.CONFIRMATION_REQUIRED,
                OperationStatus.APPROVAL_REQUIRED,
                OperationStatus.DISPATCHED,
                OperationStatus.CANCELLED,
                OperationStatus.MANUAL_REQUIRED,
            }
        ),
        OperationStatus.CONFIRMATION_REQUIRED: frozenset(
            {
                OperationStatus.APPROVAL_REQUIRED,
                OperationStatus.DISPATCHED,
                OperationStatus.CANCELLED,
                OperationStatus.MANUAL_REQUIRED,
            }
        ),
        OperationStatus.APPROVAL_REQUIRED: frozenset(
            {
                OperationStatus.DISPATCHED,
                OperationStatus.CANCELLED,
                OperationStatus.MANUAL_REQUIRED,
            }
        ),
        OperationStatus.DISPATCHED: frozenset(
            {
                OperationStatus.PENDING,
                OperationStatus.SUCCEEDED,
                OperationStatus.FAILED,
                OperationStatus.UNKNOWN,
                OperationStatus.MANUAL_REQUIRED,
            }
        ),
        OperationStatus.PENDING: frozenset(
            {
                OperationStatus.SUCCEEDED,
                OperationStatus.FAILED,
                OperationStatus.UNKNOWN,
                OperationStatus.MANUAL_REQUIRED,
            }
        ),
        OperationStatus.FAILED: frozenset(
            {OperationStatus.DISPATCHED, OperationStatus.MANUAL_REQUIRED}
        ),
        OperationStatus.UNKNOWN: frozenset(
            {
                OperationStatus.PENDING,
                OperationStatus.SUCCEEDED,
                OperationStatus.FAILED,
                OperationStatus.MANUAL_REQUIRED,
            }
        ),
        OperationStatus.SUCCEEDED: frozenset(),
        OperationStatus.CANCELLED: frozenset(),
        OperationStatus.MANUAL_REQUIRED: frozenset(),
    }
)

_IN_FLIGHT: frozenset[OperationStatus] = frozenset(
    {
        OperationStatus.CREATED,
        OperationStatus.CONFIRMATION_REQUIRED,
        OperationStatus.APPROVAL_REQUIRED,
        OperationStatus.DISPATCHED,
        OperationStatus.PENDING,
    }
)


@dataclass(frozen=True, slots=True)
class Operation:
    id: str
    case_id: str
    action_type: ActionType
    action_id: str
    request_fingerprint: str
    status: OperationStatus
    state_version: int
    attempt: int
    error_class: ErrorClass
    requested_at: datetime
    confirmed_at: datetime | None = None
    approved_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    provider_ref: str | None = None
    result_code: str | None = None
    trace_id: str | None = None


def is_operation_terminal(status: OperationStatus) -> bool:
    return not OPERATION_TRANSITIONS[status]


def request_fingerprint(
    *,
    action_type: ActionType,
    case_id: str,
    payload: Mapping[str, Any],
) -> str:
    # 用 sha256 而不是 hash()：后者受 PYTHONHASHSEED 影响，重启后幂等键会变。
    canonical = json.dumps(
        {
            "action_type": action_type.value,
            "case_id": case_id,
            "payload": _normalise(payload),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def classify_replay(*, existing: Operation | None, fingerprint: str) -> ReplayVerdict:
    # 指纹不一致必须最先判：那种情况下 existing 的状态无关紧要，
    # 调用方拿着同一个幂等键换了参数，直接拒。
    if existing is None:
        return ReplayVerdict.FIRST_ATTEMPT
    if existing.request_fingerprint != fingerprint:
        return ReplayVerdict.FINGERPRINT_MISMATCH
    if existing.status is OperationStatus.SUCCEEDED:
        return ReplayVerdict.ALREADY_SUCCEEDED
    if existing.status in _IN_FLIGHT:
        return ReplayVerdict.IN_FLIGHT
    if existing.status is OperationStatus.UNKNOWN:
        return ReplayVerdict.NEEDS_RECONCILE
    if existing.status is OperationStatus.FAILED:
        return ReplayVerdict.RETRYABLE
    # CANCELLED / MANUAL_REQUIRED：终态，不再执行。
    return ReplayVerdict.ALREADY_SUCCEEDED


def _normalise(value: Any) -> Any:
    # 唯一实质要求：Decimal("199.00") 与 "199.00" 必须归一到同一串，
    # 否则同一请求换个类型就绕过了幂等检查。其余类型交给 json 的 default=str。
    if isinstance(value, Mapping):
        return {str(k): _normalise(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_normalise(v) for v in value]
    if isinstance(value, Decimal | str):
        try:
            return format(Decimal(value).normalize(), "f")
        except (ArithmeticError, ValueError):
            return value
    return value
