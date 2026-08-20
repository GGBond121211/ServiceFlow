from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from serviceflow.agent.model import StructuredModel
from serviceflow.api.dependencies import SessionFactory
from serviceflow.api.routes import router

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
    )
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
