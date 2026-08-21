from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.infrastructure.database import create_database_engine, create_session_factory

engine = create_database_engine()
SessionFactory = create_session_factory(engine)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
