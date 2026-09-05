"""SqlAlchemyCheckpointSaver：LangGraph checkpoint 落关系库，替代 InMemorySaver。

三张表复现检查点持久化契约；checkpoint 是恢复上下文不是事实源；每个方法各自 commit；只实现异步接口。
"""

from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import UTC, datetime
from typing import Any

from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from langgraph.checkpoint.serde.base import SerializerProtocol
from sqlalchemy import delete, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from serviceflow.infrastructure.tables import (
    CheckpointBlobRow,
    CheckpointRow,
    CheckpointWriteRow,
)

_ASYNC_ONLY = (
    "SqlAlchemyCheckpointSaver 只提供异步接口，请用 aget_tuple / alist / aput / "
    "aput_writes。同步桥接会在事件循环里阻塞。"
)


class SqlAlchemyCheckpointSaver(BaseCheckpointSaver[str]):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        serde: SerializerProtocol | None = None,
    ) -> None:
        super().__init__(serde=serde)
        self._session_factory = session_factory

    # --- 写 -----------------------------------------------------------------

    async def aput(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> dict[str, Any]:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")

        body = dict(checkpoint)
        values: dict[str, Any] = body.pop("channel_values", {})
        checkpoint_type, checkpoint_blob = self.serde.dumps_typed(body)
        metadata_type, metadata_blob = self.serde.dumps_typed(
            get_checkpoint_metadata(config, metadata)
        )

        async with self._session_factory() as session:
            for channel, version in new_versions.items():
                if channel in values:
                    blob_type, blob = self.serde.dumps_typed(values[channel])
                else:
                    # 通道存在但这一版没有值。记类型不记内容，读回时跳过。
                    blob_type, blob = "empty", b""
                await _upsert(
                    session,
                    CheckpointBlobRow,
                    keys={
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "channel": channel,
                        "version": str(version),
                    },
                    values={"blob_type": blob_type, "blob": blob},
                )
            await _upsert(
                session,
                CheckpointRow,
                keys={
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "id": checkpoint["id"],
                },
                values={
                    "parent_checkpoint_id": parent_checkpoint_id,
                    "checkpoint_type": checkpoint_type,
                    "checkpoint_blob": checkpoint_blob,
                    "metadata_type": metadata_type,
                    "metadata_blob": metadata_blob,
                    "created_at": datetime.now(UTC),
                },
            )
            await session.commit()

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def aput_writes(
        self,
        config: dict[str, Any],
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]

        async with self._session_factory() as session:
            for index, (channel, value) in enumerate(writes):
                idx = WRITES_IDX_MAP.get(channel, index)
                write_type, write_blob = self.serde.dumps_typed(value)
                keys = {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                    "task_id": task_id,
                    "idx": idx,
                }
                if idx >= 0:
                    # idx >= 0 表示普通写：同一 (task, idx) 已存在就不覆盖，
                    # 与 InMemorySaver 的 `continue` 语义一致。
                    existing = await session.get(
                        CheckpointWriteRow, tuple(keys.values())
                    )
                    if existing is not None:
                        continue
                await _upsert(
                    session,
                    CheckpointWriteRow,
                    keys=keys,
                    values={
                        "channel": channel,
                        "write_type": write_type,
                        "write_blob": write_blob,
                        "task_path": task_path,
                    },
                )
            await session.commit()

    async def adelete_thread(self, thread_id: str) -> None:
        async with self._session_factory() as session:
            for table in (CheckpointWriteRow, CheckpointBlobRow, CheckpointRow):
                await session.execute(delete(table).where(table.thread_id == thread_id))
            await session.commit()

    # --- 读 -----------------------------------------------------------------

    async def aget_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)

        async with self._session_factory() as session:
            statement = select(CheckpointRow).where(
                CheckpointRow.thread_id == thread_id,
                CheckpointRow.checkpoint_ns == checkpoint_ns,
            )
            if checkpoint_id:
                statement = statement.where(CheckpointRow.id == checkpoint_id)
            else:
                statement = statement.order_by(CheckpointRow.id.desc()).limit(1)
            row = await session.scalar(statement)
            if row is None:
                return None
            return await self._to_tuple(session, row)

    async def alist(
        self,
        config: dict[str, Any] | None,
        *,
        filter: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        statement = select(CheckpointRow).order_by(CheckpointRow.id.desc())
        if config is not None:
            statement = statement.where(
                CheckpointRow.thread_id == config["configurable"]["thread_id"]
            )
            checkpoint_ns = config["configurable"].get("checkpoint_ns")
            if checkpoint_ns is not None:
                statement = statement.where(CheckpointRow.checkpoint_ns == checkpoint_ns)
            if checkpoint_id := get_checkpoint_id(config):
                statement = statement.where(CheckpointRow.id == checkpoint_id)
        if before is not None and (before_id := get_checkpoint_id(before)):
            statement = statement.where(CheckpointRow.id < before_id)

        async with self._session_factory() as session:
            rows = (await session.scalars(statement)).all()
            remaining = limit
            for row in rows:
                if remaining is not None and remaining <= 0:
                    return
                candidate = await self._to_tuple(session, row)
                # metadata 过滤放在反序列化之后：它存的是 blob，SQL 层筛不了。
                if filter and not all(
                    value == candidate.metadata.get(key) for key, value in filter.items()
                ):
                    continue
                if remaining is not None:
                    remaining -= 1
                yield candidate

    async def _to_tuple(self, session: AsyncSession, row: CheckpointRow) -> CheckpointTuple:
        body: Checkpoint = self.serde.loads_typed((row.checkpoint_type, row.checkpoint_blob))
        metadata = self.serde.loads_typed((row.metadata_type, row.metadata_blob))
        channel_values = await self._load_blobs(
            session,
            thread_id=row.thread_id,
            checkpoint_ns=row.checkpoint_ns,
            versions=body.get("channel_versions", {}),
        )
        writes = await session.scalars(
            select(CheckpointWriteRow)
            .where(
                CheckpointWriteRow.thread_id == row.thread_id,
                CheckpointWriteRow.checkpoint_ns == row.checkpoint_ns,
                CheckpointWriteRow.checkpoint_id == row.id,
            )
            .order_by(CheckpointWriteRow.task_id, CheckpointWriteRow.idx)
        )
        parent_config = None
        if row.parent_checkpoint_id:
            parent_config = {
                "configurable": {
                    "thread_id": row.thread_id,
                    "checkpoint_ns": row.checkpoint_ns,
                    "checkpoint_id": row.parent_checkpoint_id,
                }
            }
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": row.thread_id,
                    "checkpoint_ns": row.checkpoint_ns,
                    "checkpoint_id": row.id,
                }
            },
            checkpoint={**body, "channel_values": channel_values},
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=[
                (
                    write.task_id,
                    write.channel,
                    self.serde.loads_typed((write.write_type, write.write_blob)),
                )
                for write in writes
            ],
        )

    async def _load_blobs(
        self,
        session: AsyncSession,
        *,
        thread_id: str,
        checkpoint_ns: str,
        versions: ChannelVersions,
    ) -> dict[str, Any]:
        if not versions:
            return {}
        rows = await session.scalars(
            select(CheckpointBlobRow).where(
                CheckpointBlobRow.thread_id == thread_id,
                CheckpointBlobRow.checkpoint_ns == checkpoint_ns,
                CheckpointBlobRow.channel.in_(list(versions)),
            )
        )
        wanted = {channel: str(version) for channel, version in versions.items()}
        loaded: dict[str, Any] = {}
        for row in rows:
            if wanted.get(row.channel) != row.version or row.blob_type == "empty":
                continue
            loaded[row.channel] = self.serde.loads_typed((row.blob_type, row.blob or b""))
        return loaded

    # --- 同步接口：明确不支持 ------------------------------------------------

    def get_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        raise NotImplementedError(_ASYNC_ONLY)

    def list(
        self,
        config: dict[str, Any] | None,
        *,
        filter: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        raise NotImplementedError(_ASYNC_ONLY)

    def put(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> dict[str, Any]:
        raise NotImplementedError(_ASYNC_ONLY)

    def put_writes(
        self,
        config: dict[str, Any],
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        raise NotImplementedError(_ASYNC_ONLY)

    def delete_thread(self, thread_id: str) -> None:
        raise NotImplementedError(_ASYNC_ONLY)


async def _upsert(
    session: AsyncSession,
    table: type[Any],
    *,
    keys: dict[str, Any],
    values: dict[str, Any],
) -> None:
    # 必须用方言原生 upsert，不能写成"先 get 再 add"——后者在并发下
    # 两个协程都读到 None，然后一起 INSERT，撞主键。
    row = {**keys, **values}
    if session.bind is not None and session.bind.dialect.name == "mysql":
        statement = mysql_insert(table).values(**row)
        await session.execute(statement.on_duplicate_key_update(**values))
        return
    statement = sqlite_insert(table).values(**row)
    await session.execute(
        statement.on_conflict_do_update(index_elements=list(keys), set_=dict(values))
    )
