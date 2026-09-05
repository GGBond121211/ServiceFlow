from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ModelProfile:
    key: str
    provider: str
    model: str
    context_length: int
    native_tool_calling: bool
    structured_output: str
    chinese_after_sales: bool
    input_cost_per_million: Decimal | None
    output_cost_per_million: Decimal | None
    cached_input_cost_per_million: Decimal | None
    price_unit: str
    priced_at: str
    price_source: str

    def supports(self, capability: str) -> bool:
        if capability == "native_tool_calling":
            return self.native_tool_calling
        if capability == "structured_output":
            return self.structured_output in {"json_mode", "json_schema"}
        if capability == "chinese_after_sales":
            return self.chinese_after_sales
        raise ValueError(f"未知模型能力: {capability}")


@dataclass(frozen=True, slots=True)
class RouteProfile:
    name: str
    version: str
    candidates: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    max_attempts_per_model: int
    deadline_seconds: float
    risk_level: str


class ModelRegistry:
    def __init__(
        self,
        *,
        models: tuple[ModelProfile, ...],
        routes: tuple[RouteProfile, ...],
    ) -> None:
        self._models = {profile.key: profile for profile in models}
        self._routes = {route.name: route for route in routes}
        if len(self._models) != len(models) or len(self._routes) != len(routes):
            raise ValueError("模型 key 和路由 name 必须唯一")
        for route in routes:
            if route.max_attempts_per_model < 1 or route.deadline_seconds <= 0:
                raise ValueError("路由尝试次数与 deadline 必须为正")
            if any(key not in self._models for key in route.candidates):
                raise ValueError(f"路由 {route.name} 引用了未登记模型")

    def route(self, name: str) -> RouteProfile:
        try:
            return self._routes[name]
        except KeyError as error:
            raise KeyError(f"未知模型路由: {name}") from error

    def candidates(self, route: RouteProfile) -> tuple[ModelProfile, ...]:
        candidates = []
        for key in route.candidates:
            profile = self._models[key]
            if all(profile.supports(item) for item in route.required_capabilities):
                candidates.append(profile)
        return tuple(candidates)

    def configured_candidates(self, route: RouteProfile) -> tuple[ModelProfile, ...]:
        return tuple(self._models[key] for key in route.candidates)


@dataclass(frozen=True, slots=True)
class RouteDriftReport:
    drifted: bool
    requires_model_ab: bool
    max_distribution_shift: float
    quality_pass_rate: float


def route_drift_report(
    *,
    baseline: dict[str, float],
    current: dict[str, float],
    quality_pass_rate: float,
    minimum_quality_pass_rate: float,
    shift_threshold: float,
) -> RouteDriftReport:
    keys = set(baseline) | set(current)
    maximum = max(abs(current.get(key, 0.0) - baseline.get(key, 0.0)) for key in keys)
    drifted = maximum > shift_threshold
    return RouteDriftReport(
        drifted=drifted,
        requires_model_ab=drifted or quality_pass_rate < minimum_quality_pass_rate,
        max_distribution_shift=maximum,
        quality_pass_rate=quality_pass_rate,
    )
