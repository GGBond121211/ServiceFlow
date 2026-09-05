import asyncio
from collections import deque
from collections.abc import Sequence
from decimal import Decimal

import pytest

from serviceflow.agent.model import NativeToolCall
from serviceflow.infrastructure.gateway_context import bind_gateway_context
from serviceflow.infrastructure.gateway_errors import GatewayErrorClass, GatewayFailure
from serviceflow.infrastructure.gateway_metrics import GatewayMetrics
from serviceflow.infrastructure.model_gateway import ModelGateway
from serviceflow.infrastructure.model_profiles import (
    ModelProfile,
    ModelRegistry,
    RouteProfile,
)
from serviceflow.infrastructure.provider_model_adapters import (
    ProviderModelRequest,
    ProviderModelResponse,
)


class FakeModelProvider:
    def __init__(
        self,
        key: str,
        script: Sequence[ProviderModelResponse | GatewayFailure],
        *,
        delay_seconds: float = 0.0,
    ) -> None:
        self.key = key
        self._script = deque(script)
        self._delay = delay_seconds
        self.calls = 0

    async def complete(
        self, profile: ModelProfile, request: ProviderModelRequest
    ) -> ProviderModelResponse:
        del profile, request
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if not self._script:
            raise GatewayFailure(GatewayErrorClass.SERVER_ERROR, "fake script exhausted")
        item = self._script.popleft()
        if isinstance(item, GatewayFailure):
            raise item
        return item


def _registry(*, backup_tools: bool = True, deadline: float = 1.0) -> ModelRegistry:
    return ModelRegistry(
        models=(
            ModelProfile(
                key="frontier-primary",
                provider="frontier",
                model="deepseek-v4-flash",
                context_length=1_000_000,
                native_tool_calling=True,
                structured_output="json_mode",
                chinese_after_sales=True,
                input_cost_per_million=Decimal("1.0"),
                output_cost_per_million=Decimal("2.0"),
                cached_input_cost_per_million=Decimal("0.1"),
                price_unit="frontier_diamond",
                priced_at="2026-09-05",
                price_source="frontier-console",
            ),
            ModelProfile(
                key="frontier-backup",
                provider="frontier",
                model="backup-low-cost",
                context_length=128_000,
                native_tool_calling=backup_tools,
                structured_output="json_mode",
                chinese_after_sales=True,
                input_cost_per_million=Decimal("0.5"),
                output_cost_per_million=Decimal("1.0"),
                cached_input_cost_per_million=Decimal("0.05"),
                price_unit="frontier_diamond",
                priced_at="2026-09-05",
                price_source="frontier-console",
            ),
        ),
        routes=(
            RouteProfile(
                name="intent-clarification",
                version="step8-v1",
                candidates=("frontier-primary", "frontier-backup"),
                required_capabilities=("structured_output", "chinese_after_sales"),
                max_attempts_per_model=1,
                deadline_seconds=deadline,
                risk_level="low",
            ),
            RouteProfile(
                name="operation-plan",
                version="step8-v1",
                candidates=("frontier-primary", "frontier-backup"),
                required_capabilities=(
                    "native_tool_calling",
                    "structured_output",
                    "chinese_after_sales",
                ),
                max_attempts_per_model=1,
                deadline_seconds=deadline,
                risk_level="high",
            ),
        ),
    )


def _success(model: str = "backup-low-cost") -> ProviderModelResponse:
    return ProviderModelResponse(
        content='{"intent":"refund"}',
        tool_calls=(),
        response_model=model,
        input_tokens=100,
        output_tokens=20,
        finish_reason="stop",
        latency_ms=12.0,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_class",
    [
        GatewayErrorClass.RATE_LIMIT,
        GatewayErrorClass.SERVER_ERROR,
        GatewayErrorClass.TIMEOUT,
        GatewayErrorClass.CONNECTION,
        GatewayErrorClass.INVALID_RESPONSE,
    ],
)
async def test_allowed_failure_falls_back_to_backup(error_class) -> None:
    primary = FakeModelProvider("frontier-primary", [GatewayFailure(error_class, "boom")])
    backup = FakeModelProvider("frontier-backup", [_success()])
    gateway = ModelGateway(_registry(), {primary.key: primary, backup.key: backup})

    result = await gateway.complete_json(system="json", user="退款")

    assert result.model == "backup-low-cost"
    assert primary.calls == 1
    assert backup.calls == 1
    audit = gateway.last_call
    assert audit is not None
    assert audit.selected_model == "backup-low-cost"
    assert audit.fallback_reason == error_class.value
    assert audit.estimated_cost == Decimal("0.000070")


@pytest.mark.asyncio
async def test_security_failure_never_calls_backup() -> None:
    primary = FakeModelProvider(
        "frontier-primary", [GatewayFailure(GatewayErrorClass.PERMISSION, "denied")]
    )
    backup = FakeModelProvider("frontier-backup", [_success()])
    gateway = ModelGateway(_registry(), {primary.key: primary, backup.key: backup})

    with pytest.raises(GatewayFailure) as caught:
        await gateway.complete_json(system="json", user="退款")

    assert caught.value.error_class is GatewayErrorClass.PERMISSION
    assert backup.calls == 0


@pytest.mark.asyncio
async def test_malformed_json_response_falls_back() -> None:
    primary = FakeModelProvider(
        "frontier-primary",
        [
            ProviderModelResponse(
                content="not-json",
                tool_calls=(),
                response_model="deepseek-v4-flash",
                input_tokens=3,
                output_tokens=2,
                finish_reason="stop",
                latency_ms=1.0,
            )
        ],
    )
    backup = FakeModelProvider("frontier-backup", [_success()])
    gateway = ModelGateway(_registry(), {primary.key: primary, backup.key: backup})

    result = await gateway.complete_json(system="json", user="退款")

    assert result.model == "backup-low-cost"
    assert gateway.last_call is not None
    assert gateway.last_call.fallback_reason == GatewayErrorClass.INVALID_RESPONSE.value


@pytest.mark.asyncio
async def test_high_risk_route_rejects_incompatible_backup() -> None:
    primary = FakeModelProvider(
        "frontier-primary", [GatewayFailure(GatewayErrorClass.RATE_LIMIT, "limited")]
    )
    backup = FakeModelProvider("frontier-backup", [_success()])
    gateway = ModelGateway(
        _registry(backup_tools=False), {primary.key: primary, backup.key: backup}
    )

    with pytest.raises(GatewayFailure) as caught:
        await gateway.complete_with_tools(
            messages=[{"role": "user", "content": "退款"}],
            tools=[{"type": "function", "function": {"name": "request_refund"}}],
        )

    assert caught.value.error_class is GatewayErrorClass.CAPABILITY
    assert caught.value.manual_required is True
    assert backup.calls == 0


@pytest.mark.asyncio
async def test_total_deadline_stops_fallback_chain() -> None:
    primary = FakeModelProvider(
        "frontier-primary",
        [GatewayFailure(GatewayErrorClass.TIMEOUT, "slow")],
        delay_seconds=0.06,
    )
    backup = FakeModelProvider("frontier-backup", [_success()], delay_seconds=0.06)
    gateway = ModelGateway(
        _registry(deadline=0.08), {primary.key: primary, backup.key: backup}
    )

    with pytest.raises(GatewayFailure) as caught:
        await gateway.complete_json(system="json", user="退款")

    assert caught.value.error_class is GatewayErrorClass.DEADLINE
    assert primary.calls == 1
    assert backup.calls == 1


@pytest.mark.asyncio
async def test_native_tool_result_is_preserved_after_fallback() -> None:
    primary = FakeModelProvider(
        "frontier-primary", [GatewayFailure(GatewayErrorClass.SERVER_ERROR, "down")]
    )
    backup = FakeModelProvider(
        "frontier-backup",
        [
            ProviderModelResponse(
                content="",
                tool_calls=(NativeToolCall("call-1", "get_order", {"order_id": "ORDER-001"}),),
                response_model="backup-low-cost",
                input_tokens=10,
                output_tokens=4,
                finish_reason="tool_calls",
                latency_ms=8.0,
            )
        ],
    )
    gateway = ModelGateway(_registry(), {primary.key: primary, backup.key: backup})

    result = await gateway.complete_with_tools(
        messages=[{"role": "user", "content": "查订单"}],
        tools=[{"type": "function", "function": {"name": "get_order"}}],
    )

    assert result.tool_calls[0].name == "get_order"
    assert result.model == "backup-low-cost"


@pytest.mark.asyncio
async def test_circuit_open_skips_unhealthy_primary() -> None:
    from serviceflow.infrastructure.model_gateway import CircuitBreaker

    primary = FakeModelProvider(
        "frontier-primary", [GatewayFailure(GatewayErrorClass.SERVER_ERROR, "down")]
    )
    backup = FakeModelProvider("frontier-backup", [_success(), _success()])
    gateway = ModelGateway(
        _registry(),
        {primary.key: primary, backup.key: backup},
        circuit_breaker=CircuitBreaker(failure_threshold=1, recovery_seconds=60),
    )

    await gateway.complete_json(system="json", user="第一次")
    await gateway.complete_json(system="json", user="第二次")

    assert primary.calls == 1
    assert backup.calls == 2
    assert gateway.last_call is not None
    assert gateway.last_call.fallback_reason == GatewayErrorClass.CIRCUIT_OPEN.value


@pytest.mark.asyncio
async def test_all_circuits_open_returns_typed_failure_without_provider_call() -> None:
    from serviceflow.infrastructure.model_gateway import CircuitBreaker

    circuit = CircuitBreaker(failure_threshold=1, recovery_seconds=60)
    primary = FakeModelProvider("frontier-primary", [])
    backup = FakeModelProvider("frontier-backup", [])
    for key in (primary.key, backup.key):
        circuit.failure(key)
    gateway = ModelGateway(
        _registry(), {primary.key: primary, backup.key: backup}, circuit_breaker=circuit
    )
    with pytest.raises(GatewayFailure) as caught:
        await gateway.complete_json(system="json", user="测试")
    assert caught.value.error_class is GatewayErrorClass.CIRCUIT_OPEN
    assert primary.calls == backup.calls == 0


class CapturingLimiter:
    def __init__(self, *, release_error: Exception | None = None) -> None:
        self.acquired: list[tuple[str, str]] = []
        self.release_error = release_error

    async def acquire(self, *, route: str, tenant_id: str):
        self.acquired.append((route, tenant_id))

        release_error = self.release_error

        class Lease:
            async def release(self) -> None:
                if release_error is not None:
                    raise release_error
                return None

        return Lease()


@pytest.mark.asyncio
async def test_request_context_drives_tenant_limit_audit_and_metrics() -> None:
    primary = FakeModelProvider("frontier-primary", [_success("deepseek-v4-flash")])
    backup = FakeModelProvider("frontier-backup", [_success()])
    limiter = CapturingLimiter()
    metrics = GatewayMetrics()
    gateway = ModelGateway(
        _registry(),
        {primary.key: primary, backup.key: backup},
        limiter=limiter,
        metrics=metrics,
    )

    with bind_gateway_context(
        tenant_id="tenant-a",
        session_id="SESSION-1",
        case_id="CASE-1",
        operation_id="OP-1",
        run_id="RUN-1",
        request_id="REQ-1",
    ):
        await gateway.complete_json(system="json", user="退款")

    assert limiter.acquired == [("intent-clarification", "tenant-a")]
    record = gateway.last_call
    assert record is not None
    assert record.tenant_id == "tenant-a"
    assert record.session_id == "SESSION-1"
    assert record.case_id == "CASE-1"
    assert record.operation_id == "OP-1"
    assert record.run_id == "RUN-1"
    assert record.request_id == "REQ-1"
    snapshot = metrics.snapshot()
    assert snapshot["routes"]["intent-clarification"]["requests_total"] == 1
    assert snapshot["routes"]["intent-clarification"]["success_total"] == 1


@pytest.mark.asyncio
async def test_lease_release_failure_does_not_discard_successful_model_response() -> None:
    primary = FakeModelProvider("frontier-primary", [_success("deepseek-v4-flash")])
    backup = FakeModelProvider("frontier-backup", [_success()])
    gateway = ModelGateway(
        _registry(),
        {primary.key: primary, backup.key: backup},
        limiter=CapturingLimiter(release_error=OSError("redis disconnected")),
    )

    result = await gateway.complete_json(system="json", user="退款")

    assert result.model == "deepseek-v4-flash"
