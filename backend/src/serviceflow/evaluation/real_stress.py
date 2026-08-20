"""通过 Docker API、真实 MySQL 和真实模型运行压力测试。

这个模块和 ``stress.py`` 的确定性回放测试分开。它只负责压测编排：

1. 把每个评测案例映射到独立的临时用户和订单；
2. 通过 Docker 暴露的 FastAPI 发送真实 HTTP 请求；
3. 由容器内的 AsyncOpenAI 调用真实模型；
4. 直接从 MySQL 读取最终业务状态；
5. 清理本轮创建的临时业务数据。

为了避免不同案例同时修改同一个 ORDER-001，消息里的原始订单号会被替换为
本轮唯一的 ORDER-数字编号。消息语义不变，数据库中的订单状态仍然按案例原始
状态初始化。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from time import perf_counter

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.agent.graph import DEMO_REFERENCE_DATE
from serviceflow.domain.models import Order
from serviceflow.evaluation.loader import DEFAULT_EVAL_PATH, load_eval_cases
from serviceflow.evaluation.models import EvalCase
from serviceflow.infrastructure.database import create_database_schema
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.tables import (
    ApprovalRow,
    OrderItemRow,
    OrderRow,
    RefundRow,
    TicketRow,
    UserRow,
)

COMPLEX_EVAL_PATH = (
    Path(__file__).parents[4]
    / "tests"
    / "eval_cases"
    / "serviceflow_v1_complex_60.jsonl"
)
DEFAULT_LEVELS = (1, 10, 50, 100)
ORDER_PATTERN = re.compile(r"ORDER-\d+")


@dataclass(frozen=True, slots=True)
class Scenario:
    case: EvalCase
    scenario_id: str
    user_id: str
    mapped_order_id: str | None
    messages: tuple[str, ...]
    order_id_map: dict[str, str]


@dataclass(slots=True)
class ScenarioRun:
    scenario: Scenario
    latency_ms: float
    request_count: int
    first_decision: str | None
    final_response: dict[str, object] | None
    error_category: str | None
    error: str | None
    actual_final_state: dict[str, str]
    passed: bool = False
    business_mismatch: str | None = None


async def run_real_pressure_test(
    *,
    cases: list[EvalCase],
    database_url: str,
    base_url: str = "http://127.0.0.1:8009",
    levels: tuple[int, ...] = DEFAULT_LEVELS,
    repeat: int = 1,
) -> dict[str, object]:
    if repeat < 1:
        raise ValueError("repeat 必须大于等于 1")
    if not cases:
        raise ValueError("至少需要一个评测案例")

    database_url = _ensure_async_database_url(database_url)
    run_seed = int(time.time()) % 100000
    scenarios = _build_scenarios(cases, repeat=repeat, run_seed=run_seed)
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    results = []
    try:
        await create_database_schema(engine)
        for level in levels:
            await _cleanup_scenarios(scenarios, session_factory)
            await _prepare_scenarios(scenarios, session_factory)
            level_result = await _run_level(
                scenarios=scenarios,
                session_factory=session_factory,
                base_url=base_url,
                concurrency=level,
            )
            results.append(level_result)
    finally:
        await _cleanup_scenarios(scenarios, session_factory)
        await engine.dispose()

    return {
        "run_at": datetime.now(UTC).isoformat(),
        "mode": "real_docker_mysql_deepseek",
        "base_url": base_url,
        "case_count_per_wave": len(cases),
        "repeat": repeat,
        "scenario_count": len(scenarios),
        "levels": results,
    }


async def _run_level(
    *,
    scenarios: list[Scenario],
    session_factory: async_sessionmaker[AsyncSession],
    base_url: str,
    concurrency: int,
) -> dict[str, object]:
    if concurrency < 1:
        raise ValueError("并发数必须大于等于 1")

    semaphore = asyncio.Semaphore(concurrency)
    active_state = {"value": 0}
    peak_state = {"value": 0}
    active_lock = asyncio.Lock()
    timeout = httpx.Timeout(180.0, connect=30.0, pool=180.0)
    limits = httpx.Limits(
        max_connections=max(100, concurrency + 20),
        max_keepalive_connections=max(50, concurrency),
    )
    started = perf_counter()
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=timeout,
        limits=limits,
        trust_env=False,
    ) as client:
        tasks = []
        for scenario in scenarios:
            tasks.append(
                _run_scenario(
                    scenario=scenario,
                    client=client,
                    semaphore=semaphore,
                    active_state=active_state,
                    peak_state=peak_state,
                    active_lock=active_lock,
                )
            )
        scenario_runs = await asyncio.gather(*tasks)

    final_states = await _read_final_states(scenarios, session_factory)
    for scenario_run in scenario_runs:
        scenario_run.actual_final_state = final_states.get(
            scenario_run.scenario.scenario_id,
            {},
        )
        _evaluate_scenario(scenario_run)

    elapsed_ms = (perf_counter() - started) * 1000
    return _level_report(
        scenario_runs=scenario_runs,
        concurrency=concurrency,
        elapsed_ms=elapsed_ms,
        peak_users=peak_state["value"],
    )


async def _run_scenario(
    *,
    scenario: Scenario,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    active_state: dict[str, int],
    peak_state: dict[str, int],
    active_lock: asyncio.Lock,
) -> ScenarioRun:
    started = 0.0
    request_count = 0
    first_decision: str | None = None
    final_response: dict[str, object] | None = None
    error_category: str | None = None
    error: str | None = None
    async with semaphore:
        started = perf_counter()
        async with active_lock:
            active_state["value"] += 1
            if active_state["value"] > peak_state["value"]:
                peak_state["value"] = active_state["value"]
        try:
            response = await _post_json(
                client,
                "/api/v1/conversations",
                {"user_id": scenario.user_id},
            )
            request_count += 1
            conversation = _require_success(response)
            thread_id = str(conversation["thread_id"])

            for message in scenario.messages:
                response = await _post_json(
                    client,
                    f"/api/v1/conversations/{thread_id}/messages",
                    {"message": message},
                )
                request_count += 1
                conversation = _require_success(response)
                if first_decision is None:
                    first_decision = _optional_text(conversation.get("decision"))
                final_response = conversation

                if _needs_approval_resume(scenario.case, conversation):
                    approval = conversation.get("approval")
                    if not isinstance(approval, dict):
                        raise RuntimeError("响应缺少待审批信息")
                    approval_id = approval.get("id")
                    response = await _post_json(
                        client,
                        f"/api/v1/conversations/{thread_id}/approvals/{approval_id}",
                        {"approved": scenario.case.approval_decision},
                    )
                    request_count += 1
                    conversation = _require_success(response)
                    final_response = conversation
        except _HttpRequestError as exc:
            error_category = exc.category
            error = str(exc)
        except Exception as exc:  # 单个案例失败不能中断其余用户。
            error_category = "client_or_business_error"
            error = f"{type(exc).__name__}: {exc}"
        finally:
            async with active_lock:
                active_state["value"] -= 1

    return ScenarioRun(
        scenario=scenario,
        latency_ms=(perf_counter() - started) * 1000,
        request_count=request_count,
        first_decision=first_decision,
        final_response=final_response,
        error_category=error_category,
        error=error,
        actual_final_state={},
    )


async def _post_json(
    client: httpx.AsyncClient,
    path: str,
    payload: dict[str, object],
) -> httpx.Response:
    try:
        return await client.post(path, json=payload)
    except httpx.TimeoutException as exc:
        raise _HttpRequestError("timeout", f"请求超时：{exc}") from exc
    except httpx.TransportError as exc:
        raise _HttpRequestError("transport_error", f"网络传输失败：{exc}") from exc


def _require_success(response: httpx.Response) -> dict[str, object]:
    if response.status_code < 200 or response.status_code >= 300:
        category = "http_4xx"
        if response.status_code == 429:
            category = "rate_limit"
        elif response.status_code >= 500:
            category = "http_5xx"
        raise _HttpRequestError(
            category,
            f"HTTP {response.status_code}: {response.text[:500]}",
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise _HttpRequestError(
            "invalid_json",
            f"HTTP {response.status_code} 返回的内容不是 JSON：{response.text[:500]}",
        ) from exc
    if not isinstance(body, dict):
        raise _HttpRequestError("invalid_json", "接口返回的 JSON 不是对象")
    return body


class _HttpRequestError(RuntimeError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


async def _prepare_scenarios(
    scenarios: list[Scenario],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        for scenario in scenarios:
            session.add(UserRow(id=scenario.user_id, display_name="真实压测用户"))

        # OrderRow.user_id 有外键约束，先把用户显式写入数据库。
        await session.flush()

        for scenario in scenarios:
            state = scenario.case.initial_state
            if scenario.mapped_order_id is None:
                continue
            if state.status is None or state.total_amount is None:
                raise ValueError(f"{scenario.scenario_id}: 初始订单状态不完整")
            delivered_at = None
            if state.delivered_days_ago is not None:
                delivered_date = date.fromisoformat(DEMO_REFERENCE_DATE) - timedelta(
                    days=state.delivered_days_ago
                )
                delivered_at = datetime.combine(
                    delivered_date,
                    datetime_time(hour=10),
                    tzinfo=UTC,
                )
            await OrderRepository(session).add(
                Order(
                    id=scenario.mapped_order_id,
                    user_id=scenario.user_id,
                    status=state.status,
                    total_amount=state.total_amount,
                    placed_at=datetime(2026, 7, 1, tzinfo=UTC),
                    delivered_at=delivered_at,
                )
            )
        await session.commit()


async def _cleanup_scenarios(
    scenarios: list[Scenario],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_ids = []
    order_ids = []
    for scenario in scenarios:
        user_ids.append(scenario.user_id)
        if scenario.mapped_order_id is not None:
            order_ids.append(scenario.mapped_order_id)

    async with session_factory() as session:
        if order_ids:
            await session.execute(delete(ApprovalRow).where(ApprovalRow.order_id.in_(order_ids)))
            await session.execute(delete(RefundRow).where(RefundRow.order_id.in_(order_ids)))
            await session.execute(delete(TicketRow).where(TicketRow.order_id.in_(order_ids)))
            await session.execute(delete(OrderItemRow).where(OrderItemRow.order_id.in_(order_ids)))
            await session.execute(delete(OrderRow).where(OrderRow.id.in_(order_ids)))
        if user_ids:
            await session.execute(delete(UserRow).where(UserRow.id.in_(user_ids)))
        await session.commit()


async def _read_final_states(
    scenarios: list[Scenario],
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, dict[str, str]]:
    states: dict[str, dict[str, str]] = {}
    async with session_factory() as session:
        for scenario in scenarios:
            state: dict[str, str] = {}
            if scenario.mapped_order_id is None:
                states[scenario.scenario_id] = state
                continue
            order = await OrderRepository(session).get(scenario.mapped_order_id)
            if order is not None:
                state["order_status"] = order.status.value
            refund = await _latest_case_row(
                session,
                RefundRow,
                scenario.mapped_order_id,
            )
            ticket = await _latest_case_row(
                session,
                TicketRow,
                scenario.mapped_order_id,
            )
            approval = await _latest_case_row(
                session,
                ApprovalRow,
                scenario.mapped_order_id,
            )
            if refund is not None:
                state["refund_status"] = str(refund.status)
            if ticket is not None:
                state["ticket_status"] = str(ticket.status)
            if approval is not None:
                state["approval_status"] = str(approval.status)
            states[scenario.scenario_id] = state
    return states


async def _latest_case_row(
    session: AsyncSession,
    row_type: object,
    order_id: str,
) -> object | None:
    statement = select(row_type).where(row_type.order_id == order_id)
    statement = statement.order_by(row_type.created_at.desc())
    statement = statement.limit(1)
    return await session.scalar(statement)


def _evaluate_scenario(scenario_run: ScenarioRun) -> None:
    if scenario_run.error is not None:
        return
    response = scenario_run.final_response
    if response is None:
        scenario_run.error_category = "empty_response"
        scenario_run.error = "没有收到最终会话响应"
        return

    expected = scenario_run.scenario.case.expected
    actual_tools = _tool_names(response)
    expected_tools = list(expected.expected_tools)
    if response.get("decision") != expected.decision.value:
        scenario_run.business_mismatch = (
            f"decision={response.get('decision')!r}, expected={expected.decision.value!r}"
        )
    elif response.get("policy_id") != expected.policy_id:
        scenario_run.business_mismatch = (
            f"policy_id={response.get('policy_id')!r}, expected={expected.policy_id!r}"
        )
    elif actual_tools != expected_tools:
        scenario_run.business_mismatch = (
            f"tools={actual_tools!r}, expected={expected_tools!r}"
        )
    else:
        expected_state = expected.final_state.model_dump(mode="json", exclude_none=True)
        if scenario_run.actual_final_state != expected_state:
            scenario_run.business_mismatch = (
                f"final_state={scenario_run.actual_final_state!r}, "
                f"expected={expected_state!r}"
            )

    if scenario_run.business_mismatch is not None:
        scenario_run.error_category = "business_mismatch"
        scenario_run.error = scenario_run.business_mismatch
        return
    scenario_run.passed = True


def _level_report(
    *,
    scenario_runs: list[ScenarioRun],
    concurrency: int,
    elapsed_ms: float,
    peak_users: int,
) -> dict[str, object]:
    latencies = []
    passed = 0
    request_count = 0
    category_counts: dict[str, int] = {}
    failures = []
    models = []
    for scenario_run in scenario_runs:
        latencies.append(scenario_run.latency_ms)
        request_count += scenario_run.request_count
        if scenario_run.passed:
            passed += 1
        if scenario_run.error_category is not None:
            current = category_counts.get(scenario_run.error_category, 0)
            category_counts[scenario_run.error_category] = current + 1
        if scenario_run.error is not None and len(failures) < 20:
            failures.append(
                {
                    "case_id": scenario_run.scenario.case.id,
                    "scenario_id": scenario_run.scenario.scenario_id,
                    "category": scenario_run.error_category,
                    "error": scenario_run.error,
                    "first_decision": scenario_run.first_decision,
                }
            )
        if scenario_run.final_response is not None:
            model_name = _optional_text(scenario_run.final_response.get("model"))
            if model_name is not None and model_name not in models:
                models.append(model_name)

    total = len(scenario_runs)
    return {
        "concurrency": concurrency,
        "scenarios": total,
        "passed": passed,
        "failed": total - passed,
        "requests": request_count,
        "elapsed_ms": round(elapsed_ms, 2),
        "throughput_scenarios_per_second": round(
            _safe_ratio(total, elapsed_ms / 1000),
            2,
        ),
        "requests_per_second": round(
            _safe_ratio(request_count, elapsed_ms / 1000),
            2,
        ),
        "latency_ms": {
            "p50": round(_percentile(latencies, 50), 2),
            "p95": round(_percentile(latencies, 95), 2),
            "p99": round(_percentile(latencies, 99), 2),
            "max": round(_percentile(latencies, 100), 2),
        },
        "peak_users": peak_users,
        "error_categories": category_counts,
        "models_seen": models,
        "failures": failures,
    }


def _build_scenarios(
    cases: list[EvalCase],
    *,
    repeat: int,
    run_seed: int,
) -> list[Scenario]:
    scenarios = []
    scenario_index = 0
    for repeat_index in range(repeat):
        for case in cases:
            order_tokens = []
            if case.initial_state.order_id is not None:
                order_tokens.append(case.initial_state.order_id)
            for message in case.messages:
                for token in ORDER_PATTERN.findall(message):
                    if token not in order_tokens:
                        order_tokens.append(token)
            order_id_map: dict[str, str] = {}
            token_index = 0
            for token in order_tokens:
                order_id_map[token] = (
                    f"ORDER-9{run_seed:05d}{scenario_index:03d}{token_index:02d}"
                )
                token_index += 1
            rewritten_messages = []
            for message in case.messages:
                rewritten_messages.append(_rewrite_order_ids(message, order_id_map))
            mapped_order_id = None
            if case.initial_state.order_id is not None:
                mapped_order_id = order_id_map[case.initial_state.order_id]
            scenarios.append(
                Scenario(
                    case=case,
                    scenario_id=f"{case.id}__repeat_{repeat_index}__index_{scenario_index}",
                    user_id=f"REAL{run_seed:05d}U{scenario_index:04d}",
                    mapped_order_id=mapped_order_id,
                    messages=tuple(rewritten_messages),
                    order_id_map=order_id_map,
                )
            )
            scenario_index += 1
    return scenarios


def _rewrite_order_ids(message: str, order_id_map: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        original = match.group(0)
        return order_id_map.get(original, original)

    return ORDER_PATTERN.sub(replace, message)


def _needs_approval_resume(case: EvalCase, response: dict[str, object]) -> bool:
    if case.approval_decision is None:
        return False
    approval = response.get("approval")
    if not isinstance(approval, dict):
        return False
    return approval.get("status") == "pending"


def _tool_names(response: dict[str, object]) -> list[str]:
    names = []
    events = response.get("tool_events", [])
    if not isinstance(events, list):
        return names
    for event in events:
        if isinstance(event, dict) and "tool" in event:
            names.append(str(event["tool"]))
    return names


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = int((percentile / 100) * len(ordered))
    if rank < 1:
        rank = 1
    if rank > len(ordered):
        rank = len(ordered)
    return ordered[rank - 1]


def load_env_value(name: str, env_path: Path) -> str | None:
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
        if key.strip() != name:
            continue
        return raw_value.strip().strip('"').strip("'")
    return None


def _ensure_async_database_url(database_url: str) -> str:
    if database_url.startswith("mysql+pymysql://"):
        return database_url.replace(
            "mysql+pymysql://",
            "mysql+aiomysql://",
            1,
        )
    return database_url


def write_real_pressure_outputs(
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
        "# ServiceFlow 真实 Docker + MySQL + DeepSeek 压力测试",
        "",
        f"- 运行时间：`{report['run_at']}`",
        f"- API 地址：`{report['base_url']}`",
        f"- 每波原始案例数：`{report['case_count_per_wave']}`",
        f"- 重复波次：`{report['repeat']}`",
        f"- 总逻辑用户数：`{report['scenario_count']}`",
        "- 模型：由 Docker API 容器真实调用，不使用回放模型",
        "",
        "| 并发用户 | 案例数 | 通过 | 失败 | 请求数 | 案例/秒 | 请求/秒 | "
        "P50 ms | P95 ms | P99 ms | 峰值用户 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    error_sections = []
    levels = report.get("levels", [])
    if isinstance(levels, list):
        for level in levels:
            if not isinstance(level, dict):
                continue
            latency = level.get("latency_ms", {})
            if not isinstance(latency, dict):
                latency = {}
            lines.append(
                "| {concurrency} | {scenarios} | {passed} | {failed} | {requests} | "
                "{throughput} | {request_rate} | {p50} | {p95} | {p99} | {peak} |".format(
                    concurrency=level.get("concurrency"),
                    scenarios=level.get("scenarios"),
                    passed=level.get("passed"),
                    failed=level.get("failed"),
                    requests=level.get("requests"),
                    throughput=level.get("throughput_scenarios_per_second"),
                    request_rate=level.get("requests_per_second"),
                    p50=latency.get("p50"),
                    p95=latency.get("p95"),
                    p99=latency.get("p99"),
                    peak=level.get("peak_users"),
                )
            )
            error_sections.append(
                (
                    level.get("concurrency"),
                    json.dumps(level.get("error_categories", {}), ensure_ascii=False),
                )
            )
    if error_sections:
        lines.append("")
        for concurrency, error_categories in error_sections:
            lines.append(f"并发 {concurrency} 的错误分类：")
            lines.append(f"`{error_categories}`")
    lines.extend(
        [
            "",
            "说明：每个案例使用独立临时用户和订单，订单号只在本轮测试中有效。测试完成后，",
            "本轮创建的用户、订单、退款、工单和审批记录会被删除，不清理原有演示数据。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="通过 Docker API、真实 MySQL 和真实模型运行压力测试"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8009")
    parser.add_argument("--database-url")
    parser.add_argument("--level", type=int, nargs="+", default=list(DEFAULT_LEVELS))
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parents[4] / "outputs" / "evaluation",
    )
    parser.add_argument("--output-stem", default="serviceflow-real-deepseek-pressure")
    args = parser.parse_args()

    cases = load_eval_cases([DEFAULT_EVAL_PATH, COMPLEX_EVAL_PATH])
    if args.limit is not None:
        cases = cases[: args.limit]
    database_url = args.database_url
    if not database_url:
        project_root = Path(__file__).parents[4]
        database_url = load_env_value("SERVICEFLOW_DATABASE_URL", project_root / ".env")
    if not database_url:
        raise SystemExit("找不到 SERVICEFLOW_DATABASE_URL，请检查 .env 或 --database-url")
    report = asyncio.run(
        run_real_pressure_test(
            cases=cases,
            database_url=database_url,
            base_url=args.base_url,
            levels=tuple(args.level),
            repeat=args.repeat,
        )
    )
    json_path, markdown_path = write_real_pressure_outputs(
        report,
        args.output,
        args.output_stem,
    )
    print(
        json.dumps(
            {
                "results": str(json_path),
                "report": str(markdown_path),
                "levels": report["levels"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
