"""Operation 幂等判定与请求指纹的确定性测试。

Step 2 只做"单进程内、数据库唯一键"级别的幂等；重试、Outbox、DLQ 在 Step 7。
但**判定逻辑**在这里就必须是纯函数且可测，否则 Step 7 无从建立。
"""

import os
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from serviceflow.domain.operations import (
    OPERATION_TRANSITIONS,
    ActionType,
    ErrorClass,
    Operation,
    OperationStatus,
    ReplayVerdict,
    classify_replay,
    is_operation_terminal,
    request_fingerprint,
)

AT = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)


def make_operation(
    status: OperationStatus,
    *,
    fingerprint: str = "fp-a",
    error_class: ErrorClass = ErrorClass.NONE,
) -> Operation:
    return Operation(
        id="OP-0001",
        case_id="CASE-0001",
        action_type=ActionType.REFUND,
        action_id="ACT-0001",
        request_fingerprint=fingerprint,
        status=status,
        state_version=1,
        attempt=1,
        error_class=error_class,
        requested_at=AT,
    )


# --- 请求指纹 ---------------------------------------------------------------


def test_fingerprint_ignores_key_order() -> None:
    a = request_fingerprint(
        action_type=ActionType.REFUND,
        case_id="CASE-1",
        payload={"amount": "199.00", "order_id": "ORDER-1"},
    )
    b = request_fingerprint(
        action_type=ActionType.REFUND,
        case_id="CASE-1",
        payload={"order_id": "ORDER-1", "amount": "199.00"},
    )
    assert a == b


def test_fingerprint_changes_when_amount_changes() -> None:
    base = request_fingerprint(
        action_type=ActionType.REFUND,
        case_id="CASE-1",
        payload={"order_id": "ORDER-1", "amount": Decimal("199.00")},
    )
    tampered = request_fingerprint(
        action_type=ActionType.REFUND,
        case_id="CASE-1",
        payload={"order_id": "ORDER-1", "amount": Decimal("1990.00")},
    )
    assert base != tampered


def test_fingerprint_normalises_decimal_and_string_amounts() -> None:
    """Decimal("199.00") 和 "199.00" 必须得到同一指纹，否则同一请求换个类型就绕过幂等。"""
    as_decimal = request_fingerprint(
        action_type=ActionType.REFUND,
        case_id="CASE-1",
        payload={"amount": Decimal("199.00")},
    )
    as_string = request_fingerprint(
        action_type=ActionType.REFUND,
        case_id="CASE-1",
        payload={"amount": "199.00"},
    )
    assert as_decimal == as_string


def test_fingerprint_distinguishes_action_type_and_case() -> None:
    payload = {"order_id": "ORDER-1"}
    refund = request_fingerprint(
        action_type=ActionType.REFUND, case_id="CASE-1", payload=payload
    )
    cancel = request_fingerprint(
        action_type=ActionType.CANCEL_ORDER, case_id="CASE-1", payload=payload
    )
    other_case = request_fingerprint(
        action_type=ActionType.REFUND, case_id="CASE-2", payload=payload
    )
    assert len({refund, cancel, other_case}) == 3


def test_fingerprint_is_stable_across_processes() -> None:
    """跨进程稳定——不能依赖 PYTHONHASHSEED，否则重启后幂等键全变。

    只起 1 个 subprocess（CLAUDE.md §2.4 R4）：设了 PYTHONHASHSEED 的子进程
    与本进程结果相同，就已经证明了指纹不依赖哈希随机化。
    """
    script = (
        "from decimal import Decimal;"
        "from serviceflow.domain.operations import ActionType, request_fingerprint;"
        "print(request_fingerprint(action_type=ActionType.REFUND, case_id='CASE-1',"
        " payload={'order_id': 'ORDER-1', 'amount': Decimal('199.00')}))"
    )
    child = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": "12345"},
    ).stdout.strip()

    assert child == request_fingerprint(
        action_type=ActionType.REFUND,
        case_id="CASE-1",
        payload={"order_id": "ORDER-1", "amount": Decimal("199.00")},
    )


# --- 重放判定 ---------------------------------------------------------------


def test_no_prior_operation_is_first_attempt() -> None:
    verdict = classify_replay(existing=None, fingerprint="fp-a")
    assert verdict is ReplayVerdict.FIRST_ATTEMPT


def test_succeeded_operation_is_replayed_not_re_executed() -> None:
    existing = make_operation(OperationStatus.SUCCEEDED)
    assert classify_replay(existing=existing, fingerprint="fp-a") is ReplayVerdict.ALREADY_SUCCEEDED


@pytest.mark.parametrize(
    "status",
    [
        OperationStatus.CREATED,
        OperationStatus.CONFIRMATION_REQUIRED,
        OperationStatus.APPROVAL_REQUIRED,
        OperationStatus.DISPATCHED,
        OperationStatus.PENDING,
    ],
)
def test_in_flight_operation_is_not_re_executed(status: OperationStatus) -> None:
    existing = make_operation(status)
    assert classify_replay(existing=existing, fingerprint="fp-a") is ReplayVerdict.IN_FLIGHT


def test_failed_operation_is_retryable() -> None:
    existing = make_operation(OperationStatus.FAILED, error_class=ErrorClass.PROVIDER_ERROR)
    assert classify_replay(existing=existing, fingerprint="fp-a") is ReplayVerdict.RETRYABLE


def test_unknown_operation_needs_reconcile_not_retry() -> None:
    """超时后不知道成没成——直接重试可能重复扣款，必须先对账。"""
    existing = make_operation(OperationStatus.UNKNOWN, error_class=ErrorClass.TIMEOUT)
    assert classify_replay(existing=existing, fingerprint="fp-a") is ReplayVerdict.NEEDS_RECONCILE


def test_same_action_id_with_different_payload_is_a_mismatch() -> None:
    """同一个 actionId 换了金额——这是最危险的一种重放，必须拒绝而不是执行。"""
    existing = make_operation(OperationStatus.SUCCEEDED, fingerprint="fp-a")
    assert (
        classify_replay(existing=existing, fingerprint="fp-b")
        is ReplayVerdict.FINGERPRINT_MISMATCH
    )


def test_fingerprint_mismatch_wins_over_every_other_verdict() -> None:
    for status in OperationStatus:
        existing = make_operation(status, fingerprint="fp-a")
        assert (
            classify_replay(existing=existing, fingerprint="fp-b")
            is ReplayVerdict.FINGERPRINT_MISMATCH
        ), f"{status} 下指纹不一致仍必须优先判为 mismatch"


def test_only_first_attempt_and_retryable_permit_side_effects() -> None:
    permitted = {ReplayVerdict.FIRST_ATTEMPT, ReplayVerdict.RETRYABLE}
    assert {v for v in ReplayVerdict if v.permits_execution} == permitted


# --- 操作状态表 -------------------------------------------------------------


def test_every_operation_status_has_a_transition_entry() -> None:
    assert set(OPERATION_TRANSITIONS) == set(OperationStatus)


def test_succeeded_operation_is_terminal() -> None:
    assert OPERATION_TRANSITIONS[OperationStatus.SUCCEEDED] == frozenset()


def test_terminal_operation_statuses() -> None:
    assert is_operation_terminal(OperationStatus.SUCCEEDED) is True
    assert is_operation_terminal(OperationStatus.CANCELLED) is True
    assert is_operation_terminal(OperationStatus.MANUAL_REQUIRED) is True
    assert is_operation_terminal(OperationStatus.DISPATCHED) is False
