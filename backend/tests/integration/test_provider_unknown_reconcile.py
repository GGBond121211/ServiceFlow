from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.application.operation_service import ProviderOperationService
from serviceflow.application.session_service import SessionService
from serviceflow.domain.cases import CaseType
from serviceflow.domain.operations import ActionType, OperationStatus
from serviceflow.domain.sessions import Channel
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.idempotency import stable_action_id
from serviceflow.infrastructure.provider_adapters import (
    FakeProviderAdapter,
    ProviderRequest,
    ProviderResponse,
    ProviderRouter,
    ProviderStatus,
)
from serviceflow.infrastructure.provider_errors import ProviderErrorClass, ProviderFailure

TRACEPARENT = "00-11111111111111111111111111111111-2222222222222222-01"


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'provider.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def open_case(factory: async_sessionmaker[AsyncSession]) -> tuple[str, str]:
    service = SessionService(factory)
    session = await service.start_session(
        tenant_id="tenant-a", user_id="USER-001", channel=Channel.EVAL
    )
    goal = await service.open_goal(
        session_id=session.id,
        order_id="ORDER-001",
        scene_code="refund",
        created_by="test",
    )
    case = await service.open_case(
        goal_id=goal.id,
        order_id="ORDER-001",
        case_type=CaseType.REFUND,
        reason="Provider UNKNOWN 测试",
    )
    return session.id, case.id


def response(status: ProviderStatus, reference: str = "provider-ref-1") -> ProviderResponse:
    return ProviderResponse(
        provider="fake-refund",
        operation="refund",
        request_id="REQUEST-UNKNOWN",
        idempotency_key="provider-key",
        status=status,
        provider_reference=reference,
    )


@pytest.mark.asyncio
async def test_timeout_becomes_unknown_then_query_reconciles_success(database) -> None:
    session_id, case_id = await open_case(database)
    fake = FakeProviderAdapter(
        "fake-refund",
        execute_script=[
            ProviderFailure(
                ProviderErrorClass.TIMEOUT,
                "timeout after dispatch",
                outcome_unknown=True,
            )
        ],
        query_script=[response(ProviderStatus.SUCCEEDED)],
    )
    service = ProviderOperationService(database, ProviderRouter([fake]))
    dispatched = await service.dispatch(
        case_id=case_id,
        action_type=ActionType.REFUND,
        provider="fake-refund",
        operation_name="refund",
        request_id="REQUEST-UNKNOWN",
        payload={"order_id": "ORDER-001"},
        run_id="RUN-001",
        session_id=session_id,
        traceparent=TRACEPARENT,
    )

    assert dispatched.operation.status is OperationStatus.UNKNOWN
    assert fake.execute_calls == 1
    reconciled = await service.reconcile(
        operation_id=dispatched.operation.id,
        traceparent=TRACEPARENT,
    )
    assert reconciled.status is OperationStatus.SUCCEEDED
    assert fake.execute_calls == 1
    assert fake.query_calls == 1


@pytest.mark.asyncio
async def test_transient_5xx_uses_bounded_retry_and_backup(database) -> None:
    session_id, case_id = await open_case(database)
    primary = FakeProviderAdapter(
        "primary",
        execute_script=[
            ProviderFailure(ProviderErrorClass.SERVER_ERROR, "500"),
            ProviderFailure(ProviderErrorClass.SERVER_ERROR, "500"),
        ],
    )
    action_id = stable_action_id(
        request_id="REQUEST-FALLBACK", operation="ticket", subject_id=case_id
    )
    backup = FakeProviderAdapter(
        "backup",
        execute_script=[
            ProviderResponse(
                provider="backup",
                operation="ticket",
                request_id="REQUEST-FALLBACK",
                idempotency_key=action_id,
                status=ProviderStatus.SUCCEEDED,
                provider_reference="backup-ref",
            )
        ],
    )
    result = await ProviderOperationService(
        database, ProviderRouter([primary, backup], attempts_per_adapter=2)
    ).dispatch(
        case_id=case_id,
        action_type=ActionType.CREATE_SUPPORT_TICKET,
        provider="primary",
        operation_name="ticket",
        request_id="REQUEST-FALLBACK",
        payload={"summary": "broken"},
        run_id="RUN-002",
        session_id=session_id,
        traceparent=TRACEPARENT,
    )

    assert result.operation.status is OperationStatus.SUCCEEDED
    assert primary.execute_calls == 2
    assert backup.execute_calls == 1


@pytest.mark.asyncio
async def test_non_retryable_error_does_not_retry_or_fallback() -> None:
    primary = FakeProviderAdapter(
        "primary",
        execute_script=[ProviderFailure(ProviderErrorClass.PERMISSION, "forbidden")],
    )
    backup = FakeProviderAdapter("backup", execute_script=[response(ProviderStatus.SUCCEEDED)])
    request = ProviderRequest("primary", "refund", 5, "REQ", "KEY", {})

    result = await ProviderRouter([primary, backup]).execute(request)

    assert result.status is ProviderStatus.FAILED
    assert result.error_class is ProviderErrorClass.PERMISSION
    assert primary.execute_calls == 1
    assert backup.execute_calls == 0
