import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class RedisClient(Protocol):
    async def get(self, key: str) -> str | bytes | None: ...

    async def set(self, key: str, value: str, ex: int) -> Any: ...

    async def delete(self, key: str) -> Any: ...


class CacheStatus(StrEnum):
    HIT = "hit"
    MISS = "miss"
    UNAVAILABLE = "unavailable"
    STORED = "stored"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class CacheRead:
    status: CacheStatus
    value: Any = None


class RedisStore:
    def __init__(self, client: RedisClient, *, key_version: str = "v1") -> None:
        self._client = client
        self._key_version = key_version

    @classmethod
    def from_url(cls, url: str, *, key_version: str = "v1") -> "RedisStore":
        from redis.asyncio import Redis

        return cls(Redis.from_url(url, decode_responses=True), key_version=key_version)

    def key(self, *, tenant_id: str, user_id: str, session_id: str | None) -> str:
        session_part = session_id or "none"
        return f"serviceflow:{self._key_version}:memory:{tenant_id}:{user_id}:{session_part}"

    async def read_json(self, key: str) -> CacheRead:
        try:
            raw = await self._client.get(key)
        except Exception:
            return CacheRead(CacheStatus.UNAVAILABLE)
        if raw is None:
            return CacheRead(CacheStatus.MISS)
        try:
            envelope = json.loads(raw)
        except (TypeError, ValueError):
            return CacheRead(CacheStatus.INVALID)
        if not isinstance(envelope, dict) or envelope.get("key_version") != self._key_version:
            return CacheRead(CacheStatus.INVALID)
        return CacheRead(CacheStatus.HIT, envelope.get("value"))

    async def write_json(self, key: str, value: Any, *, ttl_seconds: int) -> CacheStatus:
        envelope = json.dumps(
            {"key_version": self._key_version, "value": value},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            await self._client.set(key, envelope, ex=ttl_seconds)
        except Exception:
            return CacheStatus.UNAVAILABLE
        return CacheStatus.STORED

    async def invalidate(self, key: str) -> CacheStatus:
        try:
            await self._client.delete(key)
        except Exception:
            return CacheStatus.UNAVAILABLE
        return CacheStatus.STORED
