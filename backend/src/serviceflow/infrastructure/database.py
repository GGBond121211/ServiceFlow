from datetime import UTC, datetime
from time import perf_counter
from typing import Any, overload

from sqlalchemy import event, text
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
    connection.execute(
        text(
            "UPDATE operations SET status = CASE status "
            "WHEN 'requested' THEN 'confirmation_required' "
            "WHEN 'confirmed' THEN 'dispatched' "
            "WHEN 'approved' THEN 'dispatched' "
            "WHEN 'started' THEN 'dispatched' "
            "WHEN 'compensated' THEN 'succeeded' "
            "WHEN 'abandoned' THEN 'manual_required' "
            "ELSE status END "
            "WHERE status IN "
            "('requested','confirmed','approved','started','compensated','abandoned')"
        )
    )


async def drop_database_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


@overload
def ensure_utc(value: datetime) -> datetime: ...


@overload
def ensure_utc(value: None) -> None: ...


def ensure_utc(value: datetime | None) -> datetime | None:
    """给从数据库读回来的 naive datetime 补上 UTC 时区。

    SQLite 不存时区，`DateTime(timezone=True)` 读回来是 naive 的；MySQL 同理。
    2.0 新增的几个 store 都要做这件事，所以放在这里共用，而不是各写一份。
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


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
