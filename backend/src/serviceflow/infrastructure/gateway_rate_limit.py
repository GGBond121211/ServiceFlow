from dataclasses import dataclass
from time import time
from typing import Any, Protocol

from serviceflow.infrastructure.gateway_errors import GatewayErrorClass, GatewayFailure

_ACQUIRE = """
local bucket = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(bucket[1]) or tonumber(ARGV[2])
local previous = tonumber(bucket[2]) or tonumber(ARGV[1])
tokens = math.min(tonumber(ARGV[2]), tokens + (tonumber(ARGV[1]) - previous) * tonumber(ARGV[3]))
local concurrent = tonumber(redis.call('GET', KEYS[2]) or '0')
if tokens < 1 then return {0, math.floor(tokens), concurrent} end
if concurrent >= tonumber(ARGV[4]) then return {-1, math.floor(tokens), concurrent} end
redis.call('HMSET', KEYS[1], 'tokens', tokens - 1, 'ts', ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[5])
redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], ARGV[5])
return {1, math.floor(tokens - 1), concurrent + 1}
"""

_RELEASE = """
local value = tonumber(redis.call('GET', KEYS[1]) or '0')
if value > 0 then return redis.call('DECR', KEYS[1]) end
return 0
"""


class RedisEvalClient(Protocol):
    async def eval(self, script: str, numkeys: int, *args: Any) -> Any: ...


@dataclass(slots=True)
class GatewayLease:
    client: RedisEvalClient
    concurrency_key: str
    remaining_tokens: int
    released: bool = False

    async def release(self) -> None:
        if self.released:
            return
        await self.client.eval(_RELEASE, 1, self.concurrency_key)
        self.released = True


class RedisGatewayLimiter:
    def __init__(
        self,
        client: RedisEvalClient,
        *,
        capacity: int,
        refill_per_second: float,
        max_concurrency: int,
        queue_limit: int = 0,
    ) -> None:
        if queue_limit != 0:
            raise ValueError("当前策略只支持 queue_limit=0 的 fail-fast backpressure")
        self._client = client
        self._capacity = capacity
        self._refill = refill_per_second
        self._max_concurrency = max_concurrency
        self._queue_limit = queue_limit

    @property
    def queue_limit(self) -> int:
        return self._queue_limit

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        capacity: int,
        refill_per_second: float,
        max_concurrency: int,
        queue_limit: int = 0,
    ) -> "RedisGatewayLimiter":
        from redis.asyncio import Redis

        return cls(
            Redis.from_url(url, decode_responses=True),
            capacity=capacity,
            refill_per_second=refill_per_second,
            max_concurrency=max_concurrency,
            queue_limit=queue_limit,
        )

    async def acquire(self, *, route: str, tenant_id: str) -> GatewayLease:
        prefix = f"serviceflow:gateway:{tenant_id}:{route}"
        now = time()
        try:
            result = await self._client.eval(
                _ACQUIRE,
                2,
                f"{prefix}:bucket",
                f"{prefix}:concurrent",
                now,
                self._capacity,
                self._refill,
                self._max_concurrency,
                60,
            )
        except Exception as error:
            raise GatewayFailure(
                GatewayErrorClass.BACKPRESSURE, "Redis 限流器不可用"
            ) from error
        allowed, remaining, _ = (int(value) for value in result)
        if allowed == 0:
            raise GatewayFailure(GatewayErrorClass.QUOTA, "Route/Tenant Token Bucket 已耗尽")
        if allowed == -1:
            raise GatewayFailure(
                GatewayErrorClass.BACKPRESSURE,
                "Gateway 并发上限已达到，queue_limit=0，立即返回 backpressure",
            )
        return GatewayLease(self._client, f"{prefix}:concurrent", remaining)
