from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from serviceflow.agent.model import StructuredModel
from serviceflow.api.dependencies import SessionFactory
from serviceflow.api.routes import router
from serviceflow.infrastructure.timing import (
    add_timing,
    collect_request_timings,
    server_timing_header,
    timing_snapshot,
)

EVALUATION_DIR = Path(__file__).parents[4] / "outputs" / "evaluation"


def create_app(
    *,
    model: StructuredModel | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> FastAPI:
    application = FastAPI(title="ServiceFlow", version="0.1.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Server-Timing", "X-ServiceFlow-Server-Ms"],
    )

    @application.middleware("http")
    async def record_request_timing(request: Request, call_next):
        with collect_request_timings():
            started_at = perf_counter()
            response = await call_next(request)
            server_ms = (perf_counter() - started_at) * 1000
            add_timing("server_ms", server_ms)
            response.headers["Server-Timing"] = server_timing_header()
            response.headers["X-ServiceFlow-Server-Ms"] = str(
                timing_snapshot().get("server_ms", 0.0)
            )
            return response

    application.state.agent_model = model
    if session_factory is None:
        application.state.agent_session_factory = SessionFactory
    else:
        application.state.agent_session_factory = session_factory
    application.state.agent_graph = None
    application.state.conversations = {}
    application.include_router(router)
    application.mount(
        "/evaluation",
        StaticFiles(directory=EVALUATION_DIR, check_dir=False),
        name="evaluation",
    )
    return application


app = create_app()
