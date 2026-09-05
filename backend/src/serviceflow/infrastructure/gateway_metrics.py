from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from math import ceil
from typing import TYPE_CHECKING

from serviceflow.infrastructure.model_profiles import RouteDriftReport, route_drift_report

if TYPE_CHECKING:
    from serviceflow.infrastructure.model_gateway import GatewayCallRecord


@dataclass(slots=True)
class _RouteMetrics:
    requests_total: int = 0
    attempts_total: int = 0
    success_total: int = 0
    failure_total: int = 0
    fallback_total: int = 0
    rate_limit_total: int = 0
    parse_failure_total: int = 0
    input_tokens_total: int = 0
    output_tokens_total: int = 0
    estimated_cost_total: Decimal = Decimal("0")
    latencies: list[float] = field(default_factory=list)
    ttfts: list[float] = field(default_factory=list)
    selected_models: Counter[str] = field(default_factory=Counter)


class GatewayMetrics:
    def __init__(self) -> None:
        self._routes: defaultdict[str, _RouteMetrics] = defaultdict(_RouteMetrics)

    def begin_request(self, *, route: str, risk_level: str) -> None:
        del risk_level
        self._routes[route].requests_total += 1

    def record(self, record: "GatewayCallRecord") -> None:
        metrics = self._routes[record.route]
        metrics.attempts_total += 1
        metrics.input_tokens_total += record.input_tokens
        metrics.output_tokens_total += record.output_tokens
        metrics.latencies.append(record.latency_ms)
        if record.ttft_ms is not None:
            metrics.ttfts.append(record.ttft_ms)
        if record.estimated_cost is not None:
            metrics.estimated_cost_total += record.estimated_cost
        if record.status == "success":
            metrics.success_total += 1
            metrics.selected_models[record.selected_model] += 1
            if record.fallback_reason is not None:
                metrics.fallback_total += 1
        else:
            metrics.failure_total += 1
            if record.error_class == "rate_limit":
                metrics.rate_limit_total += 1
            if record.error_class == "invalid_response":
                metrics.parse_failure_total += 1

    def snapshot(self) -> dict[str, object]:
        return {
            "routes": {
                route: _snapshot(metrics)
                for route, metrics in sorted(self._routes.items())
            }
        }

    def route_drift(
        self,
        *,
        route: str,
        baseline: dict[str, float],
        quality_pass_rate: float,
        minimum_quality_pass_rate: float,
        shift_threshold: float,
    ) -> RouteDriftReport:
        selected = self._routes[route].selected_models
        total = sum(selected.values())
        current = (
            {model: count / total for model, count in selected.items()} if total else {}
        )
        return route_drift_report(
            baseline=baseline,
            current=current,
            quality_pass_rate=quality_pass_rate,
            minimum_quality_pass_rate=minimum_quality_pass_rate,
            shift_threshold=shift_threshold,
        )


def _snapshot(metrics: _RouteMetrics) -> dict[str, object]:
    return {
        "requests_total": metrics.requests_total,
        "attempts_total": metrics.attempts_total,
        "success_total": metrics.success_total,
        "failure_total": metrics.failure_total,
        "fallback_total": metrics.fallback_total,
        "rate_limit_total": metrics.rate_limit_total,
        "parse_failure_total": metrics.parse_failure_total,
        "input_tokens_total": metrics.input_tokens_total,
        "output_tokens_total": metrics.output_tokens_total,
        "estimated_cost_total": str(metrics.estimated_cost_total.quantize(Decimal("0.000001"))),
        "latency_ms_avg": _average(metrics.latencies),
        "latency_ms_p95": _percentile(metrics.latencies, 0.95),
        "ttft_ms_avg": _average(metrics.ttfts),
        "ttft_ms_p95": _percentile(metrics.ttfts, 0.95),
        "selected_models": dict(sorted(metrics.selected_models.items())),
    }


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, ceil(len(ordered) * percentile) - 1)]
