import os
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from serviceflow.agent.model import StructuredModel
from serviceflow.api.dependencies import SessionFactory
from serviceflow.api.routes import router
from serviceflow.config import get_policy_retriever, get_redis_store
from serviceflow.infrastructure.database import create_database_schema
from serviceflow.infrastructure.otel import Telemetry
from serviceflow.infrastructure.prometheus_metrics import (
    prometheus_payload,
    record_http_request,
)
from serviceflow.infrastructure.timing import (
    add_timing,
    collect_request_timings,
    server_timing_header,
    timing_snapshot,
)

EVALUATION_DIR = Path(__file__).parents[4] / "outputs" / "evaluation"
BUNDLED_EVALUATION_DIR = Path(__file__).parents[1] / "evaluation" / "public"
EVALUATION_REPORT = "serviceflow-v1-report.md"


def create_app(
    *,
    model: StructuredModel | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    telemetry: Telemetry | None = None,
) -> FastAPI:
    owns_session_factory = session_factory is None
    owns_telemetry = telemetry is None

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        await create_database_schema(application.state.agent_session_factory.kw["bind"])
        await application.state.policy_retriever.prepare()
        yield
        if owns_session_factory:
            await application.state.agent_session_factory.kw["bind"].dispose()
        if owns_telemetry:
            application.state.telemetry.shutdown()

    application = FastAPI(title="ServiceFlow", version="0.1.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Server-Timing", "X-ServiceFlow-Server-Ms"],
    )

    @application.middleware("http")
    async def record_request_timing(request: Request, call_next):
        incoming = request.headers.get("traceparent")
        try:
            trace_span = application.state.telemetry.span(
                "http.request",
                traceparent=incoming,
                attributes={"http.request.method": request.method, "url.path": request.url.path},
            )
        except ValueError:
            trace_span = application.state.telemetry.span("http.request")
        with trace_span:
            with collect_request_timings():
                started_at = perf_counter()
                response = await call_next(request)
                server_ms = (perf_counter() - started_at) * 1000
                record_http_request(
                    method=request.method,
                    status=response.status_code,
                    duration_seconds=server_ms / 1000,
                )
                add_timing("server_ms", server_ms)
                response.headers["Server-Timing"] = server_timing_header()
                response.headers["X-ServiceFlow-Server-Ms"] = str(
                    timing_snapshot().get("server_ms", 0.0)
                )
                response.headers["traceparent"] = (
                    application.state.telemetry.current_traceparent()
                )
                return response

    application.state.telemetry = telemetry or Telemetry.from_env(
        sample_ratio=float(os.getenv("SERVICEFLOW_TRACE_SAMPLE_RATIO", "1"))
    )
    application.state.agent_model = model
    if session_factory is None:
        application.state.agent_session_factory = SessionFactory
    else:
        application.state.agent_session_factory = session_factory
    application.state.redis_store = get_redis_store()
    application.state.policy_retriever = get_policy_retriever(application.state.telemetry)

    application.state.agent_graph = None
    application.include_router(router)

    @application.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        payload, content_type = prometheus_payload()
        return Response(content=payload, media_type=content_type)

    evaluation_dir = (
        EVALUATION_DIR
        if (EVALUATION_DIR / EVALUATION_REPORT).is_file()
        else BUNDLED_EVALUATION_DIR
    )
    application.mount(
        "/evaluation",
        StaticFiles(directory=evaluation_dir),
        name="evaluation",
    )
    return application


app = create_app()
