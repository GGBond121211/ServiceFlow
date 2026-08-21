"""在真实 MySQL 上对比售后最新记录查询的改造前后效果。

这个实验故意把数据库查询从大模型耗时中单独分离出来：

1. 在真实 MySQL 中为同一个订单写入多条退款、工单和审批历史记录；
2. 用旧查询读取全部历史记录，并通过 ``IGNORE INDEX`` 复现改造前的执行计划；
3. 用新查询读取一条最新记录，并让 MySQL 自己选择联合索引；
4. 对比 EXPLAIN、实际返回行数和多轮查询延迟；
5. 实验结束后只删除本轮创建的测试数据。

真实模型的端到端回归由 ``real_stress.py`` 负责。两者必须同时看：数据库基准说明
SQL 改造是否有效，真实模型压测说明改造没有破坏完整业务链路。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.infrastructure.database import create_database_schema
from serviceflow.infrastructure.tables import (
    ApprovalRow,
    OrderRow,
    RefundRow,
    TicketRow,
    UserRow,
)

DEFAULT_OUTPUT_DIR = Path(__file__).parents[4] / "outputs" / "evaluation"
DEFAULT_HISTORY_ROWS = 2000
DEFAULT_NOISE_ORDER_COUNT = 100
DEFAULT_NOISE_ROWS_PER_ORDER = 180
DEFAULT_ITERATIONS = 30
DEFAULT_WARMUP = 5


@dataclass(frozen=True, slots=True)
class BenchmarkTable:
    name: str
    new_index: str
    old_index: str
    columns: str


TABLES = (
    BenchmarkTable(
        name="refunds",
        new_index="ix_refunds_order_created_at",
        old_index="ix_refunds_order_id",
        columns="id, order_id, amount, status, created_at",
    ),
    BenchmarkTable(
        name="tickets",
        new_index="ix_tickets_order_created_at",
        old_index="ix_tickets_order_id",
        columns="id, order_id, kind, status, summary, created_at",
    ),
    BenchmarkTable(
        name="approvals",
        new_index="ix_approvals_order_created_at",
        old_index="ix_approvals_order_id",
        columns="id, order_id, requested_action, status, created_at",
    ),
)


async def run_database_benchmark(
    *,
    database_url: str,
    history_rows: int = DEFAULT_HISTORY_ROWS,
    noise_order_count: int = DEFAULT_NOISE_ORDER_COUNT,
    noise_rows_per_order: int = DEFAULT_NOISE_ROWS_PER_ORDER,
    iterations: int = DEFAULT_ITERATIONS,
    warmup: int = DEFAULT_WARMUP,
) -> dict[str, object]:
    if history_rows < 2:
        raise ValueError("history_rows 必须大于等于 2")
    if noise_order_count < 1:
        raise ValueError("noise_order_count 必须大于等于 1")
    if noise_rows_per_order < 1:
        raise ValueError("noise_rows_per_order 必须大于等于 1")
    if iterations < 1:
        raise ValueError("iterations 必须大于等于 1")
    if warmup < 0:
        raise ValueError("warmup 不能小于 0")

    database_url = _ensure_async_database_url(database_url)
    seed = int(time.time()) % 1000000
    user_id = f"DBBENCH-U-{seed:06d}"
    order_id = f"ORDER-BENCH-{seed:06d}"
    noise_order_ids = []
    for index in range(noise_order_count):
        noise_order_ids.append(f"ORDER-BENCH-{seed:06d}-N{index:03d}")
    all_order_ids = [order_id, *noise_order_ids]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        await create_database_schema(engine)
        await _prepare_history(
            session_factory=session_factory,
            user_id=user_id,
            order_id=order_id,
            history_rows=history_rows,
            noise_order_ids=noise_order_ids,
            noise_rows_per_order=noise_rows_per_order,
            seed=seed,
        )
        table_results = []
        async with session_factory() as session:
            for table in TABLES:
                table_results.append(
                    await _benchmark_table(
                        session=session,
                        table=table,
                        order_id=order_id,
                        iterations=iterations,
                        warmup=warmup,
                    )
                )
    finally:
        await _cleanup_history(
            session_factory=session_factory,
            user_id=user_id,
            order_ids=all_order_ids,
        )
        await engine.dispose()

    return {
        "run_at": datetime.now(UTC).isoformat(),
        "mode": "real_mysql_database_benchmark",
        "history_rows_per_table": history_rows,
        "noise_order_count": noise_order_count,
        "noise_rows_per_noise_order": noise_rows_per_order,
        "total_rows_per_table": history_rows + noise_order_count * noise_rows_per_order,
        "iterations": iterations,
        "warmup": warmup,
        "tables": table_results,
        "note": "before 查询使用旧单列索引并读取全部历史记录；after 查询使用新联合索引并 LIMIT 1。",
    }


async def _benchmark_table(
    *,
    session: AsyncSession,
    table: BenchmarkTable,
    order_id: str,
    iterations: int,
    warmup: int,
) -> dict[str, object]:
    before_sql = _before_sql(table)
    after_sql = _after_sql(table)
    before_plan = await _explain(session, before_sql, order_id)
    after_plan = await _explain(session, after_sql, order_id)
    before_measurement = await _measure_query(
        session=session,
        statement=before_sql,
        order_id=order_id,
        iterations=iterations,
        warmup=warmup,
    )
    after_measurement = await _measure_query(
        session=session,
        statement=after_sql,
        order_id=order_id,
        iterations=iterations,
        warmup=warmup,
    )
    return {
        "table": table.name,
        "before": {
            "index": table.old_index,
            "query": before_sql,
            "plan": before_plan,
            "measurement": before_measurement,
        },
        "after": {
            "index": table.new_index,
            "query": after_sql,
            "plan": after_plan,
            "measurement": after_measurement,
        },
    }


def _before_sql(table: BenchmarkTable) -> str:
    return (
        f"SELECT {table.columns} FROM {table.name} "
        f"USE INDEX ({table.old_index}) "
        "WHERE order_id = :order_id "
        "ORDER BY created_at DESC"
    )


def _after_sql(table: BenchmarkTable) -> str:
    return (
        f"SELECT {table.columns} FROM {table.name} "
        "WHERE order_id = :order_id "
        "ORDER BY created_at DESC LIMIT 1"
    )


async def _explain(
    session: AsyncSession,
    statement: str,
    order_id: str,
) -> dict[str, object]:
    result = await session.execute(
        text(f"EXPLAIN {statement}"),
        {"order_id": order_id},
    )
    row = result.mappings().first()
    if row is None:
        return {}
    return {
        "type": _text_or_empty(row.get("type")),
        "key": _text_or_empty(row.get("key")),
        "rows": _number_or_zero(row.get("rows")),
        "filtered": _number_or_zero(row.get("filtered")),
        "extra": _text_or_empty(row.get("Extra")),
    }


async def _measure_query(
    *,
    session: AsyncSession,
    statement: str,
    order_id: str,
    iterations: int,
    warmup: int,
) -> dict[str, object]:
    for _ in range(warmup):
        await _fetch_rows(session, statement, order_id)

    latencies = []
    rows_returned = 0
    for _ in range(iterations):
        started = perf_counter()
        rows = await _fetch_rows(session, statement, order_id)
        elapsed_ms = (perf_counter() - started) * 1000
        latencies.append(elapsed_ms)
        rows_returned = len(rows)

    return {
        "iterations": iterations,
        "rows_returned": rows_returned,
        "average_ms": round(statistics.fmean(latencies), 4),
        "p50_ms": round(_percentile(latencies, 50), 4),
        "p95_ms": round(_percentile(latencies, 95), 4),
        "min_ms": round(min(latencies), 4),
        "max_ms": round(max(latencies), 4),
    }


async def _fetch_rows(
    session: AsyncSession,
    statement: str,
    order_id: str,
) -> list[object]:
    result = await session.execute(text(statement), {"order_id": order_id})
    return result.fetchall()


async def _prepare_history(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    user_id: str,
    order_id: str,
    history_rows: int,
    noise_order_ids: list[str],
    noise_rows_per_order: int,
    seed: int,
) -> None:
    now = datetime.now(UTC)
    all_order_ids = [order_id, *noise_order_ids]
    async with session_factory() as session:
        session.add(UserRow(id=user_id, display_name="数据库基准测试用户"))
        await session.flush()
        orders = []
        for current_order_id in all_order_ids:
            orders.append(
                OrderRow(
                    id=current_order_id,
                    user_id=user_id,
                    status="paid",
                    total_amount="199.00",
                    placed_at=now,
                    delivered_at=None,
                )
            )
        session.add_all(orders)
        await session.flush()

        refund_rows = []
        ticket_rows = []
        approval_rows = []
        for order_index, current_order_id in enumerate(all_order_ids):
            row_count = history_rows
            if order_index > 0:
                row_count = noise_rows_per_order
            for row_index in range(row_count):
                created_at = now - timedelta(seconds=row_index)
                row_suffix = f"{order_index:03d}-{row_index:05d}"
                refund_rows.append(
                    RefundRow(
                        id=f"DBR-{seed:06d}-{row_suffix}",
                        order_id=current_order_id,
                        amount="199.00",
                        status="completed",
                        created_at=created_at,
                    )
                )
                ticket_rows.append(
                    TicketRow(
                        id=f"DBT-{seed:06d}-{row_suffix}",
                        order_id=current_order_id,
                        kind="exchange",
                        status="open",
                        summary="数据库查询基准测试记录",
                        created_at=created_at,
                    )
                )
                approval_rows.append(
                    ApprovalRow(
                        id=f"DBA-{seed:06d}-{row_suffix}",
                        order_id=current_order_id,
                        requested_action="refund",
                        status="pending",
                        created_at=created_at,
                    )
                )
        session.add_all(refund_rows)
        session.add_all(ticket_rows)
        session.add_all(approval_rows)
        await session.commit()


async def _cleanup_history(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    user_id: str,
    order_ids: list[str],
) -> None:
    async with session_factory() as session:
        await session.execute(delete(ApprovalRow).where(ApprovalRow.order_id.in_(order_ids)))
        await session.execute(delete(RefundRow).where(RefundRow.order_id.in_(order_ids)))
        await session.execute(delete(TicketRow).where(TicketRow.order_id.in_(order_ids)))
        await session.execute(delete(OrderRow).where(OrderRow.id.in_(order_ids)))
        await session.execute(delete(UserRow).where(UserRow.id == user_id))
        await session.commit()


def _percentile(values: list[float], percentile: int) -> float:
    ordered = sorted(values)
    rank = int((percentile / 100) * len(ordered))
    if rank < 1:
        rank = 1
    if rank > len(ordered):
        rank = len(ordered)
    return ordered[rank - 1]


def _text_or_empty(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _number_or_zero(value: object) -> float | int:
    if value is None:
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number.is_integer():
        return int(number)
    return number


def _ensure_async_database_url(database_url: str) -> str:
    if database_url.startswith("mysql+pymysql://"):
        return database_url.replace(
            "mysql+pymysql://",
            "mysql+aiomysql://",
            1,
        )
    return database_url


def _load_env_value(name: str, env_path: Path) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        if key.strip() == name:
            return raw_value.strip().strip('"').strip("'")
    return None


def write_database_benchmark_output(
    report: dict[str, object],
    output_dir: Path,
    stem: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")
    return json_path, markdown_path


def _markdown_report(report: dict[str, object]) -> str:
    lines = [
        "# ServiceFlow 真实 MySQL 查询优化实验",
        "",
        f"- 运行时间：`{report['run_at']}`",
        f"- 目标订单每张表历史记录数：`{report['history_rows_per_table']}`",
        f"- 其他订单数：`{report['noise_order_count']}`",
        f"- 其他订单每张表记录数：`{report['noise_rows_per_noise_order']}`",
        f"- 每张表总记录数：`{report['total_rows_per_table']}`",
        f"- 预热次数：`{report['warmup']}`",
        f"- 测量次数：`{report['iterations']}`",
        "",
        "| 表 | 改造前索引 | 改造后索引 | 前 rows | 后 rows | 前 P95 ms | 后 P95 ms | "
        "前 Extra | 后 Extra |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    tables = report.get("tables", [])
    if isinstance(tables, list):
        for item in tables:
            if not isinstance(item, dict):
                continue
            before = item.get("before", {})
            after = item.get("after", {})
            if not isinstance(before, dict) or not isinstance(after, dict):
                continue
            before_plan = before.get("plan", {})
            after_plan = after.get("plan", {})
            before_measurement = before.get("measurement", {})
            after_measurement = after.get("measurement", {})
            if not isinstance(before_plan, dict) or not isinstance(after_plan, dict):
                continue
            if not isinstance(before_measurement, dict) or not isinstance(after_measurement, dict):
                continue
            lines.append(
                "| {table} | {before_index} | {after_index} | {before_rows} | {after_rows} | "
                "{before_p95} | {after_p95} | `{before_extra}` | `{after_extra}` |".format(
                    table=item.get("table"),
                    before_index=before.get("index"),
                    after_index=after.get("index"),
                    before_rows=before_measurement.get("rows_returned"),
                    after_rows=after_measurement.get("rows_returned"),
                    before_p95=before_measurement.get("p95_ms"),
                    after_p95=after_measurement.get("p95_ms"),
                    before_extra=before_plan.get("extra", ""),
                    after_extra=after_plan.get("extra", ""),
                )
            )
    lines.extend(
        [
            "",
            "改造前查询使用旧单列索引并读取全部历史记录；改造后查询使用联合索引和"
            "数据库侧 LIMIT 1。",
            "实验结束后会删除本轮创建的用户、订单和售后历史记录。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="在真实 MySQL 上测量最新售后记录查询优化")
    parser.add_argument("--database-url")
    parser.add_argument("--history-rows", type=int, default=DEFAULT_HISTORY_ROWS)
    parser.add_argument(
        "--noise-order-count",
        type=int,
        default=DEFAULT_NOISE_ORDER_COUNT,
    )
    parser.add_argument(
        "--noise-rows-per-order",
        type=int,
        default=DEFAULT_NOISE_ROWS_PER_ORDER,
    )
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-stem", default="serviceflow-mysql-query-benchmark")
    args = parser.parse_args()

    database_url = args.database_url
    if not database_url:
        project_root = Path(__file__).parents[4]
        database_url = _load_env_value(
            "SERVICEFLOW_DATABASE_URL",
            project_root / ".env",
        )
    if not database_url:
        raise SystemExit("找不到 SERVICEFLOW_DATABASE_URL，请检查 .env 或 --database-url")

    report = asyncio.run(
        run_database_benchmark(
            database_url=database_url,
            history_rows=args.history_rows,
            noise_order_count=args.noise_order_count,
            noise_rows_per_order=args.noise_rows_per_order,
            iterations=args.iterations,
            warmup=args.warmup,
        )
    )
    json_path, markdown_path = write_database_benchmark_output(
        report,
        args.output,
        args.output_stem,
    )
    print(
        json.dumps(
            {
                "results": str(json_path),
                "report": str(markdown_path),
                "tables": report["tables"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
