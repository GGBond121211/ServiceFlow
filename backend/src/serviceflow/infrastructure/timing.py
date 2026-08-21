from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter

_current_timings: ContextVar[dict[str, float] | None] = ContextVar(
    "serviceflow_request_timings",
    default=None,
)


@contextmanager
def collect_request_timings() -> Iterator[dict[str, float]]:
    """为当前异步请求创建独立的分阶段耗时容器。"""
    timings: dict[str, float] = {}
    token = _current_timings.set(timings)
    try:
        yield timings
    finally:
        _current_timings.reset(token)


@contextmanager
def measure_timing(name: str) -> Iterator[None]:
    """累计一个同步或异步代码块的耗时。"""
    started_at = perf_counter()
    try:
        yield
    finally:
        add_timing(name, (perf_counter() - started_at) * 1000)


def add_timing(name: str, duration_ms: float) -> None:
    timings = _current_timings.get()
    if timings is None:
        return
    current = timings.get(name, 0.0)
    timings[name] = current + duration_ms


def timing_snapshot() -> dict[str, float]:
    timings = _current_timings.get()
    if timings is None:
        return {}
    snapshot: dict[str, float] = {}
    for name, duration_ms in timings.items():
        snapshot[name] = round(duration_ms, 3)
    return snapshot


def server_timing_header() -> str:
    parts = []
    for name, duration_ms in timing_snapshot().items():
        parts.append(f"{name};dur={duration_ms:.3f}")
    return ", ".join(parts)
