from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from serviceflow.config import get_database_url


class Base(DeclarativeBase):
    pass


def create_database_engine(database_url: str | None = None) -> AsyncEngine:
    if database_url is None:
        database_url = get_database_url()
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False)


async def create_database_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(ensure_database_schema)


def ensure_database_schema(connection: Connection) -> None:
    """创建缺失的表和索引，兼容已经存在的 MySQL 数据库。"""
    Base.metadata.create_all(connection)
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            index.create(connection, checkfirst=True)


async def drop_database_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
