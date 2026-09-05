from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.agent.context_assembler import ContextAssembler
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.redis_store import CacheStatus, RedisStore


class MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int) -> None:
        self.values[key] = value

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)


class DownRedis:
    async def get(self, key: str) -> str:
        raise ConnectionError("redis stopped")

    async def set(self, key: str, value: str, ex: int) -> None:
        raise ConnectionError("redis stopped")

    async def delete(self, key: str) -> None:
        raise ConnectionError("redis stopped")


@pytest_asyncio.fixture
async def database(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'redis.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_cache_aside_warms_then_hits() -> None:
    store = RedisStore(MemoryRedis())
    key = store.key(tenant_id="tenant-a", user_id="USER-001", session_id="session-1")

    first = await store.read_json(key)
    await store.write_json(key, [{"id": "MEM-1", "content": {"language": "中文"}}], ttl_seconds=60)
    second = await store.read_json(key)

    assert first.status is CacheStatus.MISS
    assert second.status is CacheStatus.HIT
    assert second.value[0]["id"] == "MEM-1"


@pytest.mark.asyncio
async def test_redis_failure_is_visible_and_does_not_block_context_read(
    database: async_sessionmaker[AsyncSession],
) -> None:
    assembler = ContextAssembler(
        session_factory=database,
        default_prompt="intent prompt",
        redis_store=RedisStore(DownRedis()),
    )

    result = await assembler.assemble(
        {"thread_id": "thread-1", "user_id": "USER-001", "tenant_id": "tenant-a"}
    )

    assert result.cache_status is CacheStatus.UNAVAILABLE
    assert result.prompt_version == "service_agent_v1"


@pytest.mark.asyncio
async def test_context_assembler_uses_warm_cache_for_session_memory(
    database: async_sessionmaker[AsyncSession],
) -> None:
    assembler = ContextAssembler(
        session_factory=database,
        default_prompt="intent prompt",
        redis_store=RedisStore(MemoryRedis()),
    )
    first = await assembler.assemble(
        {
            "thread_id": "thread-1",
            "user_id": "USER-001",
            "tenant_id": "tenant-a",
            "confirmed_memories": [
                {"confirmed": True, "content": {"language": "中文"}, "confidence": 1}
            ],
        }
    )
    second = await assembler.assemble(
        {"thread_id": "thread-1", "user_id": "USER-001", "tenant_id": "tenant-a"}
    )

    assert first.cache_status is CacheStatus.MISS
    assert second.cache_status is CacheStatus.HIT
    assert "language=中文" in second.prompt_content
