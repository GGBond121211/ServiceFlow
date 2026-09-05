import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.application.operation_service import ProviderOperationService
from serviceflow.application.session_service import SessionService
from serviceflow.domain.cases import CaseType
from serviceflow.domain.operations import ActionType, ReplayVerdict
from serviceflow.domain.sessions import Channel
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.idempotency import stable_action_id
from serviceflow.infrastructure.provider_adapters import (
    FakeProviderAdapter,
    ProviderResponse,
    ProviderRouter,
    ProviderStatus,
)

TRACEPARENT = "00-55555555555555555555555555555555-6666666666666666-01"


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'idempotency.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def open_case(factory: async_sessionmaker[AsyncSession]) -> str:
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
        reason="并发幂等测试",
    )
    return case.id


@pytest.mark.asyncio
async def test_twenty_concurrent_requests_create_one_operation(database) -> None:
    case_id = await open_case(database)
    service = SessionService(database)
    action_id = stable_action_id(
        request_id="REQUEST-001", operation="refund", subject_id=case_id
    )
    results = await asyncio.gather(
        *[
            service.begin_operation(
                case_id=case_id,
                action_type=ActionType.REFUND,
                action_id=action_id,
                payload={"order_id": "ORDER-001", "amount": "199.00"},
            )
            for _ in range(20)
        ]
    )

    assert sum(result.verdict is ReplayVerdict.FIRST_ATTEMPT for result in results) == 1
    assert await service.count_operations(case_id) == 1


@pytest.mark.asyncio
async def test_same_key_with_changed_parameters_is_rejected(database) -> None:
    case_id = await open_case(database)
    service = SessionService(database)
    action_id = stable_action_id(
        request_id="REQUEST-002", operation="refund", subject_id=case_id
    )
    await service.begin_operation(
        case_id=case_id,
        action_type=ActionType.REFUND,
        action_id=action_id,
        payload={"amount": "199.00"},
    )
    changed = await service.begin_operation(
        case_id=case_id,
        action_type=ActionType.REFUND,
        action_id=action_id,
        payload={"amount": "899.00"},
    )

    assert changed.verdict is ReplayVerdict.FINGERPRINT_MISMATCH
    assert changed.may_execute is False


@pytest.mark.asyncio
async def test_twenty_concurrent_dispatches_call_provider_once(database) -> None:
    case_id = await open_case(database)
    action_id = stable_action_id(
        request_id="REQUEST-SIDE-EFFECT", operation="refund", subject_id=case_id
    )
    fake = FakeProviderAdapter(
        "fake-refund",
        execute_script=[
            ProviderResponse(
                provider="fake-refund",
                operation="refund",
                request_id="REQUEST-SIDE-EFFECT",
                idempotency_key=action_id,
                status=ProviderStatus.SUCCEEDED,
                provider_reference="REF-001",
            )
        ],
    )
    service = ProviderOperationService(database, ProviderRouter([fake]))
    results = await asyncio.gather(
        *[
            service.dispatch(
                case_id=case_id,
                action_type=ActionType.REFUND,
                provider="fake-refund",
                operation_name="refund",
                request_id="REQUEST-SIDE-EFFECT",
                payload={"order_id": "ORDER-001", "amount": "199.00"},
                run_id="RUN-001",
                session_id="SESSION-001",
                traceparent=TRACEPARENT,
            )
            for _ in range(20)
        ]
    )

    assert fake.execute_calls == 1
    assert len(fake.side_effect_keys) == 1
    assert len({result.operation.id for result in results}) == 1
