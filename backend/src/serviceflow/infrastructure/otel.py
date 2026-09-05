import json
import logging
import os
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from serviceflow.infrastructure.trace_context import validate_traceparent
from serviceflow.infrastructure.trace_sampling import parent_consistent_sampler

# 锁定 OTel GenAI semantic conventions v1.37 experimental 字段名。
SEMCONV_VERSION = "1.37.0-experimental"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_TTFT = "gen_ai.response.time_to_first_chunk"
SERVICEFLOW_ROUTE = "serviceflow.route"
SERVICEFLOW_ROUTE_VERSION = "serviceflow.route_version"
SERVICEFLOW_FALLBACK_REASON = "serviceflow.fallback_reason"


class Telemetry:
    def __init__(self, provider: TracerProvider, exporter: InMemorySpanExporter) -> None:
        self._provider = provider
        self._exporter = exporter
        self._tracer = provider.get_tracer("serviceflow", SEMCONV_VERSION)

    @classmethod
    def in_memory(cls, *, sample_ratio: float) -> "Telemetry":
        exporter = InMemorySpanExporter()
        provider = TracerProvider(
            sampler=parent_consistent_sampler(sample_ratio),
            resource=Resource.create(
                {"service.name": os.getenv("OTEL_SERVICE_NAME", "serviceflow")}
            ),
        )
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        return cls(provider, exporter)

    @classmethod
    def from_env(cls, *, sample_ratio: float) -> "Telemetry":
        telemetry = cls.in_memory(sample_ratio=sample_ratio)
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            telemetry._provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
            )
        return telemetry

    def shutdown(self) -> None:
        self._provider.shutdown()

    @contextmanager
    def span(
        self,
        name: str,
        *,
        traceparent: str | None = None,
        attributes: dict[str, Any] | None = None,
    ):
        context = None
        if traceparent is not None:
            context = extract({"traceparent": validate_traceparent(traceparent)})
        with self._tracer.start_as_current_span(
            name, context=context, attributes=attributes or {}
        ) as current:
            yield current

    def current_traceparent(self) -> str:
        return current_traceparent()

    def finished_spans(self):
        return tuple(self._exporter.get_finished_spans())


def current_traceparent() -> str:
    carrier: dict[str, str] = {}
    inject(carrier)
    value = carrier.get("traceparent")
    if value is None or not trace.get_current_span().get_span_context().is_valid:
        raise RuntimeError("当前没有有效 Trace Span")
    return value


def current_trace_id() -> str:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        raise RuntimeError("当前没有有效 Trace Span")
    return format(context.trace_id, "032x")


def structured_log(event: str, *, level: int = logging.INFO, **attributes: object) -> str:
    context = trace.get_current_span().get_span_context()
    trace_id = format(context.trace_id, "032x") if context.is_valid else None
    payload = {
        "event": event,
        "trace_id": trace_id,
        "span_id": format(context.span_id, "016x") if context.is_valid else None,
        "service.name": "serviceflow",
        "environment": os.getenv("SERVICEFLOW_ENVIRONMENT", "local"),
        "requestId": trace_id,
        **attributes,
    }
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    logging.getLogger("serviceflow").log(level, rendered)
    return rendered
