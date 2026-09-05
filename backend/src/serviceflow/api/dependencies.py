from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.infrastructure.database import create_database_engine, create_session_factory

engine = create_database_engine()
SessionFactory = create_session_factory(engine)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.agent_session_factory() as session:
        yield session
