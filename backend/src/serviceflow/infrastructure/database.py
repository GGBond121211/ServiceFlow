from time import perf_counter
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from serviceflow.config import get_database_url
from serviceflow.infrastructure.timing import add_timing


class Base(DeclarativeBase):
    pass


def create_database_engine(database_url: str | None = None) -> AsyncEngine:
    if database_url is None:
        database_url = get_database_url()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    _install_sql_timing(engine)
    return engine


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


def _install_sql_timing(engine: AsyncEngine) -> None:
    def before_cursor_execute(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        del connection, cursor, statement, parameters, executemany
        context._serviceflow_query_started_at = perf_counter()

    def after_cursor_execute(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        del connection, cursor, statement, parameters, executemany
        started_at = getattr(context, "_serviceflow_query_started_at", None)
        if started_at is None:
            return
        add_timing("sql_execute_ms", (perf_counter() - started_at) * 1000)

    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine.sync_engine, "after_cursor_execute", after_cursor_execute)
