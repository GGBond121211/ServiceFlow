import json
import os
from contextlib import asynccontextmanager
from secrets import compare_digest
from time import perf_counter, time
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response

from serviceflow.agent.model import ModelResult, NativeModelResult
from serviceflow.api.dependencies import SessionFactory
from serviceflow.infrastructure.audit_store import GatewayAuditWriter
from serviceflow.infrastructure.database import create_database_schema
from serviceflow.infrastructure.gateway_context import (
    GatewayRequestContext,
    bind_gateway_context,
)
from serviceflow.infrastructure.gateway_errors import GatewayErrorClass, GatewayFailure
from serviceflow.infrastructure.model_gateway import ModelGateway, build_model_gateway_from_env
from serviceflow.infrastructure.otel import Telemetry
from serviceflow.infrastructure.prometheus_metrics import (
    prometheus_payload,
    record_http_request,
)


def create_gateway_app(
    gateway: ModelGateway | Any | None = None,
    *,
    internal_key: str | None = None,
    telemetry: Telemetry | None = None,
) -> FastAPI:
    owns_telemetry = telemetry is None
    telemetry = telemetry or Telemetry.from_env(
        sample_ratio=float(os.getenv("SERVICEFLOW_TRACE_SAMPLE_RATIO", "1"))
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if application.state.gateway is None:
            if not application.state.internal_key:
                raise RuntimeError("Gateway 缺少 SERVICEFLOW_GATEWAY_INTERNAL_KEY")
            await create_database_schema(SessionFactory.kw["bind"])
            application.state.gateway = build_model_gateway_from_env(
                telemetry=telemetry,
                audit_sink=GatewayAuditWriter(SessionFactory),
            )
        yield
        if owns_telemetry:
            telemetry.shutdown()

    application = FastAPI(
        title="ServiceFlow LLM Gateway", version="step8.1-v1", lifespan=lifespan
    )
    application.state.gateway = gateway
    application.state.telemetry = telemetry
    application.state.internal_key = internal_key or os.getenv(
        "SERVICEFLOW_GATEWAY_INTERNAL_KEY"
    )

    @application.middleware("http")
    async def trace_http(request: Request, call_next):
        incoming = request.headers.get("traceparent")
        try:
            span = telemetry.span("gateway.http", traceparent=incoming)
        except ValueError:
            span = telemetry.span("gateway.http")
        with span:
            started_at = perf_counter()
            response = await call_next(request)
            record_http_request(
                method=request.method,
                status=response.status_code,
                duration_seconds=(perf_counter() - started_at),
            )
            response.headers["traceparent"] = telemetry.current_traceparent()
            response.headers["x-serviceflow-gateway-instance"] = os.getenv(
                "SERVICEFLOW_GATEWAY_INSTANCE", "local"
            )
            return response

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "instance": os.getenv("SERVICEFLOW_GATEWAY_INSTANCE", "local"),
        }

    @application.get("/internal/traces")
    async def traces(request: Request) -> dict[str, object]:
        _authorize(request, application.state.internal_key)
        spans = telemetry.finished_spans()[-100:]
        return {
            "spans": [
                {
                    "name": span.name,
                    "trace_id": format(span.context.trace_id, "032x"),
                    "span_id": format(span.context.span_id, "016x"),
                    "parent_span_id": (
                        format(span.parent.span_id, "016x") if span.parent else None
                    ),
                    "attributes": dict(span.attributes),
                }
                for span in spans
            ]
        }

    @application.get("/internal/metrics")
    async def metrics(request: Request) -> dict[str, object]:
        _authorize(request, application.state.internal_key)
        gateway_metrics = getattr(application.state.gateway, "metrics", None)
        return gateway_metrics.snapshot() if gateway_metrics is not None else {"routes": {}}

    @application.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        payload, content_type = prometheus_payload()
        return Response(content=payload, media_type=content_type)

    @application.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> dict[str, object]:
        _authorize(request, application.state.internal_key)
        payload = await request.json()
        if payload.get("stream") is True:
            raise HTTPException(status_code=422, detail="streaming_not_supported")
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise HTTPException(status_code=422, detail="messages_required")
        tools = payload.get("tools") or []
        try:
            context = GatewayRequestContext.from_headers(request.headers)
            with bind_gateway_context(**_context_values(context)):
                if tools:
                    route_name = request.headers.get("x-serviceflow-route", "operation-plan")
                    routed_completion = getattr(
                        application.state.gateway, "complete_with_tools_for_route", None
                    )
                    if routed_completion is None:
                        result = await application.state.gateway.complete_with_tools(
                            messages=messages, tools=tools
                        )
                    else:
                        result = await routed_completion(
                            route_name=route_name, messages=messages, tools=tools
                        )
                    return _native_response(result)
                routed_json = getattr(
                    application.state.gateway, "complete_json_messages", None
                )
                if routed_json is not None:
                    result = await routed_json(messages=messages)
                else:
                    system, user = _last_system_and_user(messages)
                    result = await application.state.gateway.complete_json(
                        system=system, user=user
                    )
                return _structured_response(result)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=422, detail="unknown_gateway_route") from error
        except GatewayFailure as error:
            raise HTTPException(
                status_code=_gateway_http_status(error.error_class),
                detail={
                    "error_class": error.error_class.value,
                    "manual_required": error.manual_required,
                },
            ) from error

    return application


def _authorize(request: Request, internal_key: str | None) -> None:
    authorization = request.headers.get("authorization", "")
    expected = f"Bearer {internal_key}" if internal_key else ""
    if not expected or not compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="gateway_unauthorized")


def _context_values(context: GatewayRequestContext) -> dict[str, str | None]:
    return {
        "tenant_id": context.tenant_id,
        "request_id": context.request_id,
        "session_id": context.session_id,
        "goal_id": context.goal_id,
        "case_id": context.case_id,
        "operation_id": context.operation_id,
        "run_id": context.run_id,
        "trace_id": context.trace_id,
    }


def _last_system_and_user(messages: list[object]) -> tuple[str, str]:
    system = ""
    user = ""
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("message_must_be_object")
        if message.get("role") == "system":
            system = str(message.get("content", ""))
        elif message.get("role") == "user":
            user = str(message.get("content", ""))
    return system, user


def _gateway_http_status(error_class: GatewayErrorClass) -> int:
    if error_class in {GatewayErrorClass.RATE_LIMIT, GatewayErrorClass.QUOTA}:
        return 429
    if error_class is GatewayErrorClass.BAD_REQUEST:
        return 400
    if error_class is GatewayErrorClass.AUTHENTICATION:
        return 401
    if error_class is GatewayErrorClass.PERMISSION:
        return 403
    if error_class in {
        GatewayErrorClass.CAPABILITY,
        GatewayErrorClass.BUSINESS_VALIDATION,
        GatewayErrorClass.POLICY,
        GatewayErrorClass.SAFETY,
        GatewayErrorClass.CONFIRMATION,
        GatewayErrorClass.APPROVAL,
        GatewayErrorClass.IDEMPOTENCY,
    }:
        return 422
    if error_class is GatewayErrorClass.INVALID_RESPONSE:
        return 502
    if error_class in {GatewayErrorClass.TIMEOUT, GatewayErrorClass.DEADLINE}:
        return 504
    return 503


def _structured_response(result: ModelResult) -> dict[str, object]:
    return _response(
        model=result.model,
        content=json.dumps(result.content, ensure_ascii=False, separators=(",", ":")),
        tool_calls=[],
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


def _native_response(result: NativeModelResult) -> dict[str, object]:
    tool_calls = [
        {
            "id": call.call_id,
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": json.dumps(call.arguments, ensure_ascii=False),
            },
        }
        for call in result.tool_calls
    ]
    return _response(
        model=result.model,
        content=result.content,
        tool_calls=tool_calls,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


def _response(
    *,
    model: str,
    content: str,
    tool_calls: list[dict[str, object]],
    input_tokens: int,
    output_tokens: int,
) -> dict[str, object]:
    return {
        "id": f"chatcmpl-{uuid4().hex}",
        "object": "chat.completion",
        "created": int(time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": tool_calls or None,
                },
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


app = create_gateway_app()
