from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.prompt_store import PromptStore


@pytest_asyncio.fixture
async def database(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'prompt.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_prompt_run_points_to_release_and_keeps_only_safe_variable_summary(
    database: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with database() as session:
        store = PromptStore(session)
        binding = await store.register(
            template_id="PT-1",
            name="service_agent",
            scene_code="after_sales_intent",
            version_id="PV-2",
            version="service_agent_v2",
            release_id="PR-2",
            content="new prompt",
            environment="test",
            tenant_id="tenant-a",
            at=now,
            change_reason="修复缺订单号时的澄清",
        )
        prompt_run = await store.record_run(
            request_id="request-1",
            run_id="run-1",
            binding=binding,
            variables={"memory_ids": ["MEM-1"], "context_sections": ["memory"]},
            at=now,
        )
        await session.commit()
        loaded = await store.get_run(prompt_run.id)

    assert loaded is not None
    assert loaded.binding.version_id == "PV-2"
    assert loaded.binding.release_id == "PR-2"
    assert loaded.variables_summary == {
        "memory_ids": ["MEM-1"],
        "context_sections": ["memory"],
    }


@pytest.mark.asyncio
async def test_prompt_variables_are_validated_before_run_is_recorded(
    database: async_sessionmaker[AsyncSession],
) -> None:
    async with database() as session:
        binding = await PromptStore(session).register(
            template_id="PT-1",
            name="service_agent",
            scene_code="after_sales_intent",
            version_id="PV-1",
            version="service_agent_v1",
            release_id="PR-1",
            content="prompt",
            environment="test",
            tenant_id=None,
            at=datetime.now(UTC),
            change_reason="test",
        )
        with pytest.raises(ValueError, match="变量缺失"):
            await PromptStore(session).record_run(
                request_id="request-1",
                run_id=None,
                binding=binding,
                variables={"memory_ids": []},
                at=datetime.now(UTC),
            )
