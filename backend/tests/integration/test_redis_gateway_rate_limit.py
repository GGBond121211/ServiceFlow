import pytest

from serviceflow.infrastructure.gateway_errors import GatewayErrorClass, GatewayFailure
from serviceflow.infrastructure.gateway_rate_limit import RedisGatewayLimiter


class FakeRedis:
    def __init__(self, results) -> None:
        self.results = list(results)
        self.calls = 0

    async def eval(self, script, numkeys, *args):
        del script, numkeys, args
        self.calls += 1
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.asyncio
async def test_redis_token_bucket_and_concurrency_lease() -> None:
    redis = FakeRedis([[1, 9, 1], 0])
    limiter = RedisGatewayLimiter(redis, capacity=10, refill_per_second=1, max_concurrency=2)

    lease = await limiter.acquire(route="operation-plan", tenant_id="tenant-a")
    await lease.release()

    assert lease.remaining_tokens == 9
    assert redis.calls == 2


@pytest.mark.asyncio
async def test_quota_and_redis_down_fail_before_model_call() -> None:
    limited = RedisGatewayLimiter(
        FakeRedis([[0, 0, 0]]), capacity=1, refill_per_second=1, max_concurrency=1
    )
    with pytest.raises(GatewayFailure) as quota:
        await limited.acquire(route="operation-plan", tenant_id="tenant-a")
    assert quota.value.error_class is GatewayErrorClass.QUOTA

    unavailable = RedisGatewayLimiter(
        FakeRedis([OSError("down")]), capacity=1, refill_per_second=1, max_concurrency=1
    )
    with pytest.raises(GatewayFailure) as backpressure:
        await unavailable.acquire(route="operation-plan", tenant_id="tenant-a")
    assert backpressure.value.error_class is GatewayErrorClass.BACKPRESSURE


def test_gateway_queue_policy_is_explicit_fail_fast() -> None:
    limiter = RedisGatewayLimiter(
        FakeRedis([]),
        capacity=1,
        refill_per_second=1,
        max_concurrency=1,
        queue_limit=0,
    )
    assert limiter.queue_limit == 0

    with pytest.raises(ValueError, match="queue_limit=0"):
        RedisGatewayLimiter(
            FakeRedis([]),
            capacity=1,
            refill_per_second=1,
            max_concurrency=1,
            queue_limit=1,
        )
