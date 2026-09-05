from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.agent.context_assembler import ContextAssembler
from serviceflow.domain.memory import confirmed_preference
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.memory_store import MemoryStore


@pytest_asyncio.fixture
async def database(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'memory.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_only_confirmed_low_risk_memory_is_loaded_and_expiry_is_applied(
    database: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with database() as session:
        store = MemoryStore(session)
        await store.save(
            confirmed_preference(
                memory_id="MEM-KEEP",
                tenant_id="tenant-a",
                user_id="USER-001",
                session_id=None,
                content={"language": "中文"},
                confidence=1,
                at=now,
                expires_at=now + timedelta(days=1),
            )
        )
        await store.save(
            confirmed_preference(
                memory_id="MEM-EXPIRED",
                tenant_id="tenant-a",
                user_id="USER-001",
                session_id=None,
                content={"tone": "简洁"},
                confidence=1,
                at=now - timedelta(days=2),
                expires_at=now - timedelta(days=1),
            )
        )
        await session.commit()

    assembler = ContextAssembler(
        session_factory=database,
        default_prompt="intent prompt",
        budget=None,
    )
    result = await assembler.assemble(
        {"thread_id": "thread-1", "user_id": "USER-001", "tenant_id": "tenant-a"}
    )

    assert result.build.kept_sections == ("session_memory",)
    assert "language=中文" in result.prompt_content
    assert "tone=简洁" not in result.prompt_content


@pytest.mark.asyncio
async def test_unconfirmed_memory_candidate_is_not_persisted(
    database: async_sessionmaker[AsyncSession],
) -> None:
    assembler = ContextAssembler(session_factory=database, default_prompt="intent prompt")
    await assembler.assemble(
        {
            "thread_id": "thread-1",
            "user_id": "USER-001",
            "tenant_id": "tenant-a",
            "confirmed_memories": [
                {"confirmed": False, "content": {"language": "中文"}, "confidence": 1}
            ],
        }
    )

    async with database() as session:
        memories = await MemoryStore(session).active_for(
            tenant_id="tenant-a",
            user_id="USER-001",
            session_id=None,
            now=datetime.now(UTC),
        )
    assert memories == ()
