import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from time import monotonic

from serviceflow.agent.model import ModelResult, NativeModelResult
from serviceflow.infrastructure.gateway_context import (
    GatewayRequestContext,
    current_gateway_context,
)
from serviceflow.infrastructure.gateway_errors import GatewayErrorClass, GatewayFailure
from serviceflow.infrastructure.gateway_metrics import GatewayMetrics
from serviceflow.infrastructure.gateway_rate_limit import RedisGatewayLimiter
from serviceflow.infrastructure.metric_labels import metric_labels
from serviceflow.infrastructure.model_profiles import ModelProfile, ModelRegistry, RouteProfile
from serviceflow.infrastructure.otel import (
    GEN_AI_INPUT_TOKENS,
    GEN_AI_OUTPUT_TOKENS,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_TTFT,
    SERVICEFLOW_ROUTE,
    SERVICEFLOW_ROUTE_VERSION,
    Telemetry,
    current_trace_id,
    structured_log,
)
from serviceflow.infrastructure.provider_model_adapters import (
    ModelProvider,
    ProviderModelRequest,
    ProviderModelResponse,
)


@dataclass(frozen=True, slots=True)
class GatewayCallRecord:
    route: str
    route_version: str
    primary_model: str
    selected_model: str
    selected_provider: str
    response_model: str
    fallback_reason: str | None
    attempt: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    latency_ms: float
    ttft_ms: float | None
    estimated_cost: Decimal | None
    price_unit: str
    capability_compatible: bool
    tenant_id: str = "default"
    request_id: str | None = None
    session_id: str | None = None
    goal_id: str | None = None
    case_id: str | None = None
    operation_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    status: str = "success"
    error_class: str | None = None
    metric_labels: dict[str, str] | None = None


AuditSink = Callable[[GatewayCallRecord], Awaitable[None]]


class CircuitBreaker:
    def __init__(self, *, failure_threshold: int = 3, recovery_seconds: float = 30.0) -> None:
        self._threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    def allow(self, key: str) -> bool:
        opened = self._opened_at.get(key)
        if opened is None:
            return True
        if monotonic() - opened >= self._recovery_seconds:
            self._opened_at.pop(key, None)
            self._failures[key] = 0
            return True
        return False

    def success(self, key: str) -> None:
        self._failures[key] = 0
        self._opened_at.pop(key, None)

    def failure(self, key: str) -> None:
        count = self._failures.get(key, 0) + 1
        self._failures[key] = count
        if count >= self._threshold:
            self._opened_at[key] = monotonic()


class ModelGateway:
    def __init__(
        self,
        registry: ModelRegistry,
        providers: dict[str, ModelProvider],
        limiter: RedisGatewayLimiter | None = None,
        telemetry: Telemetry | None = None,
        audit_sink: AuditSink | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        metrics: GatewayMetrics | None = None,
    ) -> None:
        self._registry = registry
        self._providers = providers
        self._limiter = limiter
        self._telemetry = telemetry
        self._audit_sink = audit_sink
        self._circuit = circuit_breaker or CircuitBreaker()
        self.metrics = metrics or GatewayMetrics()
        self.calls: list[GatewayCallRecord] = []

    @property
    def last_call(self) -> GatewayCallRecord | None:
        return self.calls[-1] if self.calls else None

    async def complete_json(self, *, system: str, user: str) -> ModelResult:
        return await self.complete_json_messages(
            messages=(
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            )
        )

    async def complete_json_messages(
        self,
        *,
        messages,
        route_name: str = "intent-clarification",
    ) -> ModelResult:
        response = await self._complete(
            route_name=route_name,
            messages=messages,
            tools=(),
            structured_output=True,
        )
        try:
            content = json.loads(response.content)
        except json.JSONDecodeError as error:
            raise GatewayFailure(
                GatewayErrorClass.INVALID_RESPONSE, "最终结构化响应不是合法 JSON"
            ) from error
        if not isinstance(content, dict):
            raise GatewayFailure(GatewayErrorClass.INVALID_RESPONSE, "结构化响应必须是对象")
        return ModelResult(
            content=content,
            model=response.response_model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

    async def complete_with_tools(self, *, messages, tools) -> NativeModelResult:
        return await self.complete_with_tools_for_route(
            route_name="operation-plan", messages=messages, tools=tools
        )

    async def complete_with_tools_for_route(
        self, *, route_name: str, messages, tools
    ) -> NativeModelResult:
        response = await self._complete(
            route_name=route_name,
            messages=messages,
            tools=tools,
            structured_output=False,
        )
        return NativeModelResult(
            content=response.content,
            tool_calls=response.tool_calls,
            model=response.response_model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

    async def _complete(
        self,
        *,
        route_name: str,
        messages,
        tools,
        structured_output: bool,
    ) -> ProviderModelResponse:
        route = self._registry.route(route_name)
        request_context = _request_context()
        self.metrics.begin_request(route=route.name, risk_level=route.risk_level)
        configured = self._registry.configured_candidates(route)
        eligible = self._registry.candidates(route)
        if not eligible:
            raise GatewayFailure(
                GatewayErrorClass.CAPABILITY,
                "路由没有满足能力要求的模型",
                manual_required=route.risk_level == "high",
            )
        lease = None
        if self._limiter is not None:
            lease = await self._limiter.acquire(
                route=route.name, tenant_id=request_context.tenant_id
            )
        span = _span(self._telemetry, route)
        try:
            with span:
                return await self._route(
                    route=route,
                    configured=configured,
                    eligible=eligible,
                    messages=messages,
                    tools=tools,
                    structured_output=structured_output,
                    request_context=request_context,
                )
        finally:
            if lease is not None:
                try:
                    await lease.release()
                except Exception:
                    structured_log(
                        "gateway_lease_release_failed",
                        level=logging.WARNING,
                        route=route.name,
                        tenant_id=request_context.tenant_id,
                    )

    async def _route(
        self,
        *,
        route: RouteProfile,
        configured: tuple[ModelProfile, ...],
        eligible: tuple[ModelProfile, ...],
        messages,
        tools,
        structured_output: bool,
        request_context: GatewayRequestContext,
    ) -> ProviderModelResponse:
        started = monotonic()
        fallback_reason = None
        attempt = 0
        last_failure = None
        for profile in eligible:
            if not self._circuit.allow(profile.key):
                fallback_reason = fallback_reason or GatewayErrorClass.CIRCUIT_OPEN.value
                continue
            provider = self._providers[profile.key]
            for _ in range(route.max_attempts_per_model):
                remaining = route.deadline_seconds - (monotonic() - started)
                if remaining <= 0:
                    raise _deadline(manual_required=route.risk_level == "high")
                attempt += 1
                attempt_started = monotonic()
                try:
                    with _provider_span(self._telemetry, profile, route) as provider_span:
                        async with asyncio.timeout(remaining):
                            response = await provider.complete(
                                profile,
                                ProviderModelRequest(
                                    messages=messages,
                                    tools=tools,
                                    structured_output=structured_output,
                                    timeout_seconds=remaining,
                                    traceparent=_traceparent(self._telemetry),
                                ),
                            )
                        if provider_span is not None:
                            provider_span.set_attribute(
                                GEN_AI_RESPONSE_MODEL, response.response_model
                            )
                            provider_span.set_attribute(GEN_AI_INPUT_TOKENS, response.input_tokens)
                            provider_span.set_attribute(
                                GEN_AI_OUTPUT_TOKENS, response.output_tokens
                            )
                            if response.ttft_ms is not None:
                                provider_span.set_attribute(GEN_AI_TTFT, response.ttft_ms)
                    _validate(response, structured_output=structured_output)
                    self._circuit.success(profile.key)
                    record = _record(
                        route,
                        configured[0],
                        profile,
                        response,
                        fallback_reason,
                        attempt,
                        request_context,
                    )
                    await self._save(record)
                    return response
                except TimeoutError as error:
                    failure = GatewayFailure(
                        GatewayErrorClass.DEADLINE,
                        "总 deadline 到期",
                        manual_required=route.risk_level == "high",
                    )
                    await self._save(
                        _failure_record(
                            route,
                            configured[0],
                            profile,
                            failure,
                            attempt,
                            attempt_started,
                            request_context,
                        )
                    )
                    structured_log(
                        "gateway_attempt_failed",
                        level=logging.WARNING,
                        route=route.name,
                        model=profile.model,
                        provider=profile.provider,
                        error_class=failure.error_class.value,
                        attempt=attempt,
                    )
                    raise failure from error
                except GatewayFailure as failure:
                    last_failure = failure
                    if failure.error_class.fallback_allowed:
                        self._circuit.failure(profile.key)
                    await self._save(
                        _failure_record(
                            route,
                            configured[0],
                            profile,
                            failure,
                            attempt,
                            attempt_started,
                            request_context,
                        )
                    )
                    if not failure.error_class.fallback_allowed:
                        raise
                    fallback_reason = fallback_reason or failure.error_class.value
        if len(eligible) < len(configured):
            raise GatewayFailure(
                GatewayErrorClass.CAPABILITY,
                "备用模型不满足当前路由能力要求",
                manual_required=route.risk_level == "high",
            )
        if monotonic() - started >= route.deadline_seconds:
            raise _deadline(manual_required=route.risk_level == "high")
        assert last_failure is not None
        if route.risk_level == "high":
            raise GatewayFailure(
                last_failure.error_class,
                str(last_failure),
                manual_required=True,
            )
        raise last_failure

    async def _save(self, record: GatewayCallRecord) -> None:
        self.calls.append(record)
        self.metrics.record(record)
        if self._audit_sink is not None:
            await self._audit_sink(record)


def _validate(response: ProviderModelResponse, *, structured_output: bool) -> None:
    if response.finish_reason not in {"stop", "tool_calls"}:
        raise GatewayFailure(GatewayErrorClass.INVALID_RESPONSE, "模型 finish_reason 无效")
    if structured_output:
        try:
            parsed = json.loads(response.content)
        except json.JSONDecodeError as error:
            raise GatewayFailure(GatewayErrorClass.INVALID_RESPONSE, "模型返回无效 JSON") from error
        if not isinstance(parsed, dict):
            raise GatewayFailure(GatewayErrorClass.INVALID_RESPONSE, "模型 JSON 必须是对象")
    elif not response.content and not response.tool_calls:
        raise GatewayFailure(GatewayErrorClass.INVALID_RESPONSE, "模型返回空响应")


def _record(
    route: RouteProfile,
    primary: ModelProfile,
    selected: ModelProfile,
    response: ProviderModelResponse,
    fallback_reason: str | None,
    attempt: int,
    request_context: GatewayRequestContext,
) -> GatewayCallRecord:
    estimated = None
    if selected.input_cost_per_million is not None and selected.output_cost_per_million is not None:
        cached_tokens = min(response.cached_input_tokens, response.input_tokens)
        uncached_tokens = response.input_tokens - cached_tokens
        cached_price = (
            selected.cached_input_cost_per_million
            if selected.cached_input_cost_per_million is not None
            else selected.input_cost_per_million
        )
        estimated = (
            Decimal(uncached_tokens) * selected.input_cost_per_million
            + Decimal(cached_tokens) * cached_price
            + Decimal(response.output_tokens) * selected.output_cost_per_million
        ) / Decimal(1_000_000)
        estimated = estimated.quantize(Decimal("0.000001"))
    return GatewayCallRecord(
        route=route.name,
        route_version=route.version,
        primary_model=primary.model,
        selected_model=selected.model,
        selected_provider=selected.provider,
        response_model=response.response_model,
        fallback_reason=fallback_reason,
        attempt=attempt,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cached_input_tokens=response.cached_input_tokens,
        latency_ms=response.latency_ms,
        ttft_ms=response.ttft_ms,
        estimated_cost=estimated,
        price_unit=selected.price_unit,
        capability_compatible=True,
        tenant_id=request_context.tenant_id,
        request_id=request_context.request_id,
        session_id=request_context.session_id,
        goal_id=request_context.goal_id,
        case_id=request_context.case_id,
        operation_id=request_context.operation_id,
        run_id=request_context.run_id,
        trace_id=request_context.trace_id,
        metric_labels=metric_labels(
            model=selected.model,
            provider=selected.provider,
            route=route.name,
            status="success",
            risk_level=route.risk_level,
        ),
    )


def _deadline(*, manual_required: bool) -> GatewayFailure:
    return GatewayFailure(
        GatewayErrorClass.DEADLINE,
        "Gateway 总 deadline 到期",
        manual_required=manual_required,
    )


def build_model_gateway_from_env(
    *,
    telemetry: Telemetry | None = None,
    audit_sink: AuditSink | None = None,
) -> ModelGateway:
    api_key = os.getenv("SERVICEFLOW_API_KEY")
    base_url = os.getenv("SERVICEFLOW_BASE_URL")
    primary_model = os.getenv("SERVICEFLOW_MODEL", "deepseek-v4-flash")
    if not api_key or not base_url:
        raise RuntimeError("Gateway 缺少 SERVICEFLOW_API_KEY 或 SERVICEFLOW_BASE_URL")
    backup_model = os.getenv("SERVICEFLOW_GATEWAY_BACKUP_MODEL", "gpt-5.6-luna")
    price_note = "Frontier 控制台定价页，用户登录态截图核对"
    primary_prices = _frontier_prices(primary_model)
    backup_prices = _frontier_prices(backup_model)
    profiles = (
        ModelProfile(
            key="frontier-primary",
            provider="frontier-shared-domain",
            model=primary_model,
            context_length=1_000_000,
            native_tool_calling=True,
            structured_output="json_mode",
            chinese_after_sales=True,
            input_cost_per_million=_optional_decimal(
                os.getenv("SERVICEFLOW_GATEWAY_PRIMARY_INPUT_COST") or primary_prices[0]
            ),
            output_cost_per_million=_optional_decimal(
                os.getenv("SERVICEFLOW_GATEWAY_PRIMARY_OUTPUT_COST") or primary_prices[1]
            ),
            cached_input_cost_per_million=_optional_decimal(
                os.getenv("SERVICEFLOW_GATEWAY_PRIMARY_CACHED_INPUT_COST")
                or primary_prices[2]
            ),
            price_unit="frontier_diamond_per_million_tokens",
            priced_at="2026-09-05",
            price_source=price_note,
        ),
        ModelProfile(
            key="frontier-backup",
            provider="frontier-shared-domain",
            model=backup_model,
            context_length=1_000_000,
            native_tool_calling=True,
            structured_output="json_mode",
            chinese_after_sales=True,
            input_cost_per_million=_optional_decimal(
                os.getenv("SERVICEFLOW_GATEWAY_BACKUP_INPUT_COST") or backup_prices[0]
            ),
            output_cost_per_million=_optional_decimal(
                os.getenv("SERVICEFLOW_GATEWAY_BACKUP_OUTPUT_COST") or backup_prices[1]
            ),
            cached_input_cost_per_million=_optional_decimal(
                os.getenv("SERVICEFLOW_GATEWAY_BACKUP_CACHED_INPUT_COST")
                or backup_prices[2]
            ),
            price_unit="frontier_diamond_per_million_tokens",
            priced_at="2026-09-05",
            price_source=price_note,
        ),
    )
    candidates = tuple(profile.key for profile in profiles)
    attempts = int(os.getenv("SERVICEFLOW_GATEWAY_ATTEMPTS_PER_MODEL", "2"))
    deadline = float(os.getenv("SERVICEFLOW_GATEWAY_DEADLINE_S", "20"))
    registry = ModelRegistry(
        models=profiles,
        routes=(
            RouteProfile(
                name="intent-clarification",
                version="step8.1-v1",
                candidates=candidates,
                required_capabilities=("structured_output", "chinese_after_sales"),
                max_attempts_per_model=attempts,
                deadline_seconds=deadline,
                risk_level="low",
            ),
            RouteProfile(
                name="operation-plan",
                version="step8.1-v1",
                candidates=candidates,
                required_capabilities=(
                    "native_tool_calling",
                    "structured_output",
                    "chinese_after_sales",
                ),
                max_attempts_per_model=attempts,
                deadline_seconds=deadline,
                risk_level="high",
            ),
            RouteProfile(
                name="policy-answer",
                version="step8.1-v1",
                candidates=candidates,
                required_capabilities=("structured_output", "chinese_after_sales"),
                max_attempts_per_model=attempts,
                deadline_seconds=deadline,
                risk_level="low",
            ),
            RouteProfile(
                name="high-risk-review",
                version="step8.1-v1",
                candidates=(profiles[0].key,),
                required_capabilities=(
                    "native_tool_calling",
                    "structured_output",
                    "chinese_after_sales",
                ),
                max_attempts_per_model=attempts,
                deadline_seconds=deadline,
                risk_level="high",
            ),
            RouteProfile(
                name="final-response",
                version="step8.1-v1",
                candidates=candidates,
                required_capabilities=("chinese_after_sales",),
                max_attempts_per_model=attempts,
                deadline_seconds=deadline,
                risk_level="low",
            ),
        ),
    )
    from serviceflow.infrastructure.provider_model_adapters import OpenAIModelProvider

    providers = {
        profile.key: OpenAIModelProvider.from_credentials(
            profile.key, api_key=api_key, base_url=base_url
        )
        for profile in profiles
    }
    limiter = None
    redis_url = os.getenv("SERVICEFLOW_REDIS_URL")
    if redis_url:
        limiter = RedisGatewayLimiter.from_url(
            redis_url,
            capacity=int(os.getenv("SERVICEFLOW_GATEWAY_BUCKET_CAPACITY", "60")),
            refill_per_second=float(os.getenv("SERVICEFLOW_GATEWAY_REFILL_PER_SECOND", "1")),
            max_concurrency=int(os.getenv("SERVICEFLOW_GATEWAY_MAX_CONCURRENCY", "8")),
            queue_limit=int(os.getenv("SERVICEFLOW_GATEWAY_QUEUE_LIMIT", "0")),
        )
    return ModelGateway(
        registry,
        providers,
        limiter=limiter,
        telemetry=telemetry,
        audit_sink=audit_sink,
    )


def _optional_decimal(value: str | None) -> Decimal | None:
    return None if value in (None, "") else Decimal(value)


def _failure_record(
    route: RouteProfile,
    primary: ModelProfile,
    selected: ModelProfile,
    failure: GatewayFailure,
    attempt: int,
    started: float,
    request_context: GatewayRequestContext,
) -> GatewayCallRecord:
    return GatewayCallRecord(
        route=route.name,
        route_version=route.version,
        primary_model=primary.model,
        selected_model=selected.model,
        selected_provider=selected.provider,
        response_model=selected.model,
        fallback_reason=failure.error_class.value,
        attempt=attempt,
        input_tokens=0,
        output_tokens=0,
        cached_input_tokens=0,
        latency_ms=(monotonic() - started) * 1000,
        ttft_ms=None,
        estimated_cost=Decimal("0"),
        price_unit=selected.price_unit,
        capability_compatible=True,
        tenant_id=request_context.tenant_id,
        request_id=request_context.request_id,
        session_id=request_context.session_id,
        goal_id=request_context.goal_id,
        case_id=request_context.case_id,
        operation_id=request_context.operation_id,
        run_id=request_context.run_id,
        trace_id=request_context.trace_id,
        status="failed",
        error_class=failure.error_class.value,
        metric_labels=metric_labels(
            model=selected.model,
            provider=selected.provider,
            route=route.name,
            status="failed",
            risk_level=route.risk_level,
            error_class=failure.error_class.value,
        ),
    )


def _span(telemetry: Telemetry | None, route: RouteProfile):
    if telemetry is None:
        from contextlib import nullcontext

        return nullcontext()
    return telemetry.span(
        "gateway.route",
        attributes={SERVICEFLOW_ROUTE: route.name, SERVICEFLOW_ROUTE_VERSION: route.version},
    )


def _provider_span(
    telemetry: Telemetry | None, profile: ModelProfile, route: RouteProfile
):
    if telemetry is None:
        from contextlib import nullcontext

        return nullcontext()
    return telemetry.span(
        "gen_ai.chat",
        attributes={
            GEN_AI_REQUEST_MODEL: profile.model,
            SERVICEFLOW_ROUTE: route.name,
            SERVICEFLOW_ROUTE_VERSION: route.version,
        },
    )


def _request_context() -> GatewayRequestContext:
    context = current_gateway_context()
    try:
        trace_id = current_trace_id()
    except RuntimeError:
        trace_id = context.trace_id
    return replace(
        context,
        trace_id=trace_id,
        request_id=context.request_id or trace_id,
    )


def _frontier_prices(model: str) -> tuple[str | None, str | None, str | None]:
    return {
        "deepseek-v4-flash": ("12", "36", "0.3996"),
        "gpt-5.6-luna": ("1.5", "12", "0.18"),
    }.get(model, (None, None, None))


def _traceparent(telemetry: Telemetry | None) -> str | None:
    if telemetry is None:
        return None
    try:
        return telemetry.current_traceparent()
    except RuntimeError:
        return None
