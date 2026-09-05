from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "serviceflow_http_requests_total",
    "HTTP requests handled by a ServiceFlow process.",
    ("method", "status"),
)
HTTP_DURATION = Histogram(
    "serviceflow_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)


def record_http_request(*, method: str, status: int, duration_seconds: float) -> None:
    HTTP_REQUESTS.labels(method=method, status=str(status)).inc()
    HTTP_DURATION.labels(method=method).observe(duration_seconds)


def prometheus_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
