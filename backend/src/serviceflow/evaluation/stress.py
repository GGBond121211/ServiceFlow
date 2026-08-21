"""ServiceFlow 异步链路压力测试。

压力测试使用评测集中的真实用户输入，但使用确定性的异步回放模型。
这样可以把模型语义质量和系统并发能力分开测量，不会因为外部模型限流、网络
抖动或费用影响结果。回放模型本身仍然通过 ``await`` 返回，能够覆盖异步
Agent、数据库、FastAPI 和 HTTP 客户端链路。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from serviceflow.agent.graph import DEMO_REFERENCE_DATE, build_service_graph
from serviceflow.agent.model import ModelResult, StructuredModel
from serviceflow.api.app import create_app
from serviceflow.domain.models import Order
from serviceflow.evaluation.loader import DEFAULT_EVAL_PATH, load_eval_cases
from serviceflow.evaluation.models import EvalCase
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.tables import UserRow

COMPLEX_EVAL_PATH = (
    Path(__file__).parents[4]
    / "tests"
    / "eval_cases"
    / "serviceflow_v1_complex_60.jsonl"
)
DEFAULT_LEVELS = (1, 10, 25, 50, 100)
ORDER_PATTERN = re.compile(r"ORDER-\d+")


@dataclass(frozen=True, slots=True)
class CaseIdentity:
    case: EvalCase
    user_id: str
    order_id: str | None


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    passed: bool
    latency_ms: float
    request_count: int
    error: str | None


class AsyncReplayModel(StructuredModel):
    """根据 100 个案例生成稳定结果的异步模型替身。"""

    def __init__(self, identities: list[CaseIdentity]) -> None:
        self._responses: dict[str, dict[str, object]] = {}
        self._active_calls = 0
        self._max_active_calls = 0
        self._counter_lock = asyncio.Lock()
        self._build_responses(identities)

    @property
    def max_active_calls(self) -> int:
        return self._max_active_calls

    async def complete_json(self, *, system: str, user: str) -> ModelResult:
        del system
        response = self._responses.get(user)
        if response is None:
            raise RuntimeError(f"回放模型没有注册这条输入：{user}")

        async with self._counter_lock:
            self._active_calls += 1
            if self._active_calls > self._max_active_calls:
                self._max_active_calls = self._active_calls

        try:
            # 主动让出事件循环，确保这条路径确实经过异步调度。
            await asyncio.sleep(0)
            return ModelResult(
                content=response,
                model="async-pressure-replay",
                input_tokens=1,
                output_tokens=1,
            )
        finally:
            async with self._counter_lock:
                self._active_calls -= 1

    def _build_responses(self, identities: list[CaseIdentity]) -> None:
        for identity in identities:
            messages = identity.case.messages
            message_index = 0
            for message in messages:
                if message in self._responses:
                    raise ValueError(f"压力测试输入重复，无法确定回放结果：{message}")
                is_last_message = message_index == len(messages) - 1
                action = _action_for_message(
                    message=message,
                    expected_action=_expected_action(identity.case),
                    is_last_message=is_last_message,
                )
                order_id = _extract_order_id(message, identity.order_id)
                issue_type = _expected_issue_type(identity.case)
                missing_fields = []
                if order_id is None:
                    missing_fields.append("order_id")
                if action is None:
                    missing_fields.append("requested_action")
                self._responses[message] = {
                    "order_id": order_id,
                    "requested_action": action,
                    "issue_type": issue_type,
                    "issue_summary": message,
                    "missing_fields": missing_fields,
                }
                message_index += 1


async def run_async_pressure_test(
    *,
    cases: list[EvalCase],
    levels: tuple[int, ...] = DEFAULT_LEVELS,
) -> dict[str, object]:
    """按多个并发档位运行全部案例，并返回可序列化的结果。"""

    identities = _build_identities(cases)
    results = []
    for level in levels:
        level_result = await _run_level(identities=identities, concurrency=level)
        results.append(level_result)

    report: dict[str, object] = {
        "run_at": datetime.now(UTC).isoformat(),
        "case_count": len(cases),
        "model_mode": "deterministic_async_replay",
        "levels": results,
    }
    return report


async def _run_level(
    *,
    identities: list[CaseIdentity],
    concurrency: int,
) -> dict[str, object]:
    import httpx

    runtime_root = Path(__file__).parents[3] / ".async-stress-runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    database_path = runtime_root / f"pressure-{concurrency}.db"
    _remove_sqlite_files(database_path)

    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"timeout": 30},
    )
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    model = AsyncReplayModel(identities)
    semaphore = asyncio.Semaphore(concurrency)
    active_state = {"value": 0}
    peak_state = {"value": 0}
    active_lock = asyncio.Lock()

    started = perf_counter()
    case_results: list[CaseResult] = []
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await _prepare_database(identities, session_factory)

        application = create_app(model=model, session_factory=session_factory)
        application.state.agent_graph = build_service_graph(
            model=model,
            session_factory=session_factory,
            checkpointer=InMemorySaver(),
        )
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://serviceflow-pressure",
        ) as client:
            tasks = []
            for identity in identities:
                tasks.append(
                    _run_user_case(
                        identity=identity,
                        client=client,
                        semaphore=semaphore,
                        session_factory=session_factory,
                        active_state=active_state,
                        active_lock=active_lock,
                        peak_state=peak_state,
                    )
                )
            case_results = await asyncio.gather(*tasks)
    finally:
        await engine.dispose()
        _remove_sqlite_files(database_path)
        shutil.rmtree(runtime_root, ignore_errors=True)

    elapsed_ms = (perf_counter() - started) * 1000
    latencies = []
    passed_cases = 0
    failed_cases = []
    request_count = 0
    http_error_count = 0
    for result in case_results:
        latencies.append(result.latency_ms)
        request_count += result.request_count
        if result.passed:
            passed_cases += 1
        if result.error is not None:
            failed_cases.append(
                {
                    "case_id": result.case_id,
                    "error": result.error,
                }
            )
            if result.error.startswith("HTTP "):
                http_error_count += 1

    return {
        "concurrency": concurrency,
        "cases": len(identities),
        "passed": passed_cases,
        "failed": len(identities) - passed_cases,
        "http_errors": http_error_count,
        "requests": request_count,
        "elapsed_ms": round(elapsed_ms, 2),
        "throughput_cases_per_second": round(
            _safe_ratio(len(identities), elapsed_ms / 1000),
            2,
        ),
        "latency_ms": {
            "p50": round(_percentile(latencies, 50), 2),
            "p95": round(_percentile(latencies, 95), 2),
            "p99": round(_percentile(latencies, 99), 2),
            "max": round(_percentile(latencies, 100), 2),
        },
        "peak_users": peak_state["value"],
        "model_peak_concurrency": model.max_active_calls,
        "failures": failed_cases[:10],
    }


async def _run_user_case(
    *,
    identity: CaseIdentity,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    session_factory: async_sessionmaker[AsyncSession],
    active_state: dict[str, int],
    active_lock: asyncio.Lock,
    peak_state: dict[str, int],
) -> CaseResult:
    started = 0.0
    request_count = 0
    error: str | None = None
    passed = False
    async with semaphore:
        started = perf_counter()
        async with active_lock:
            active_state["value"] += 1
            if active_state["value"] > peak_state["value"]:
                peak_state["value"] = active_state["value"]
        try:
            response = await client.post(
                "/api/v1/conversations",
                json={"user_id": identity.user_id},
            )
            request_count += 1
            if response.status_code != 201:
                raise RuntimeError(_http_error(response))
            conversation = response.json()
            thread_id = str(conversation["thread_id"])

            for message in identity.case.messages:
                response = await client.post(
                    f"/api/v1/conversations/{thread_id}/messages",
                    json={"message": message},
                )
                request_count += 1
                if response.status_code != 200:
                    raise RuntimeError(_http_error(response))
                conversation = response.json()
                if _should_resume_approval(identity.case, conversation):
                    approval = conversation.get("approval")
                    if not isinstance(approval, dict):
                        raise RuntimeError("响应缺少待审批信息")
                    approval_id = approval.get("id")
                    response = await client.post(
                        f"/api/v1/conversations/{thread_id}/approvals/{approval_id}",
                        json={
                            "approved": identity.case.approval_decision,
                        },
                    )
                    request_count += 1
                    if response.status_code != 200:
                        raise RuntimeError(_http_error(response))
                    conversation = response.json()

            await _assert_expected_response(
                identity.case,
                conversation,
                identity.order_id,
                session_factory,
            )
            passed = True
        except Exception as exc:  # 压测必须记录单个用户失败，不能吞掉整批结果。
            error = f"{type(exc).__name__}: {exc}"
        finally:
            async with active_lock:
                active_state["value"] -= 1

    return CaseResult(
        case_id=identity.case.id,
        passed=passed,
        latency_ms=(perf_counter() - started) * 1000,
        request_count=request_count,
        error=error,
    )


async def _prepare_database(
    identities: list[CaseIdentity],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        for identity in identities:
            session.add(UserRow(id=identity.user_id, display_name="压力测试用户"))
            state = identity.case.initial_state
            if identity.order_id is None:
                continue
            if state.status is None or state.total_amount is None:
                raise ValueError(f"{identity.case.id}: 订单初始状态不完整")
            delivered_at = None
            if state.delivered_days_ago is not None:
                delivered_date = date_from_reference() - timedelta(
                    days=state.delivered_days_ago
                )
                delivered_at = datetime.combine(
                    delivered_date,
                    time(hour=10),
                    tzinfo=UTC,
                )
            order = Order(
                id=identity.order_id,
                user_id=identity.user_id,
                status=state.status,
                total_amount=state.total_amount,
                placed_at=datetime(2026, 7, 1, tzinfo=UTC),
                delivered_at=delivered_at,
            )
            await OrderRepository(session).add(order)
        await session.commit()


def date_from_reference() -> date:
    return datetime.fromisoformat(DEMO_REFERENCE_DATE).date()


def _build_identities(cases: list[EvalCase]) -> list[CaseIdentity]:
    identities = []
    for index, case in enumerate(cases):
        user_id = f"LOAD-USER-{index:03d}"
        order_id = None
        if case.initial_state.order_id is not None:
            order_id = f"LOAD-{index:03d}-{case.initial_state.order_id}"
        identities.append(
            CaseIdentity(
                case=case,
                user_id=user_id,
                order_id=order_id,
            )
        )
    return identities


def _expected_action(case: EvalCase) -> str | None:
    if case.expected.intent is None:
        return None
    return case.expected.intent.value


def _expected_issue_type(case: EvalCase) -> str:
    if case.expected.issue_type is None:
        return "none"
    return case.expected.issue_type.value


def _extract_order_id(message: str, mapped_order_id: str | None) -> str | None:
    if mapped_order_id is None:
        return None
    match = ORDER_PATTERN.search(message)
    if match is None:
        return None
    return mapped_order_id


def _action_for_message(
    *,
    message: str,
    expected_action: str | None,
    is_last_message: bool,
) -> str | None:
    if expected_action is None:
        return None
    if is_last_message:
        return expected_action

    candidates = []
    if _contains_any(message, ("取消", "撤掉", "撤销", "不要", "不需要", "别寄")):
        candidates.append("cancel")
    if _contains_any(
        message,
        ("退款", "退钱", "退回", "退掉", "退货", "原路回来", "钱回来"),
    ):
        candidates.append("refund")
    if _contains_any(message, ("换货", "换一个", "换个", "换新", "更换")):
        candidates.append("exchange")
    if _contains_any(message, ("维修", "修一下", "修好", "修理", "师傅检查")):
        candidates.append("repair")
    if _contains_any(message, ("查询", "查一下", "状态", "到哪", "哪个环节")):
        candidates.append("query")

    if expected_action in candidates:
        return expected_action
    if candidates:
        return candidates[0]
    return None


def _contains_any(message: str, phrases: tuple[str, ...]) -> bool:
    for phrase in phrases:
        if phrase in message:
            return True
    return False


def _should_resume_approval(case: EvalCase, response: dict[str, object]) -> bool:
    if case.approval_decision is None:
        return False
    approval = response.get("approval")
    if not isinstance(approval, dict):
        return False
    return approval.get("status") == "pending"


async def _assert_expected_response(
    case: EvalCase,
    response: dict[str, object],
    order_id: str | None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    expected = case.expected
    actual_tools = []
    events = response.get("tool_events", [])
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict) and "tool" in event:
                actual_tools.append(str(event["tool"]))
    if response.get("decision") != expected.decision.value:
        raise AssertionError(
            f"decision={response.get('decision')!r}, expected={expected.decision.value!r}"
        )
    if response.get("policy_id") != expected.policy_id:
        raise AssertionError(
            f"policy_id={response.get('policy_id')!r}, expected={expected.policy_id!r}"
        )
    if actual_tools != list(expected.expected_tools):
        raise AssertionError(
            f"tools={actual_tools!r}, expected={list(expected.expected_tools)!r}"
        )
    actual_state = response.get("final_business_state", {})
    if isinstance(actual_state, dict):
        actual_state = dict(actual_state)
    else:
        actual_state = {}
    expected_state = expected.final_state.model_dump(mode="json", exclude_none=True)
    if (
        "order_status" in expected_state
        and "order_status" not in actual_state
        and order_id is not None
    ):
        async with session_factory() as session:
            saved_order = await OrderRepository(session).get(order_id)
        if saved_order is not None:
            actual_state["order_status"] = saved_order.status.value
    if actual_state != expected_state:
        raise AssertionError(f"final_state={actual_state!r}, expected={expected_state!r}")


def _http_error(response: httpx.Response) -> str:
    return f"HTTP {response.status_code}: {response.text[:300]}"


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


def _remove_sqlite_files(database_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{database_path}{suffix}")
        path.unlink(missing_ok=True)


def write_pressure_outputs(
    report: dict[str, object],
    output_dir: Path,
    stem: str = "serviceflow-async-pressure",
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
        "# ServiceFlow 异步全链路压力测试",
        "",
        f"- 运行时间：`{report['run_at']}`",
        f"- 案例数：`{report['case_count']}`（基础 40 + 复杂 60）",
        "- 模型模式：确定性异步回放，不调用外部模型 API",
        "",
        "| 并发用户数 | 通过 | 失败 | 请求数 | 吞吐（案例/秒） | "
        "P50 ms | P95 ms | P99 ms | 峰值用户 | 模型峰值并发 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    levels = report.get("levels", [])
    if isinstance(levels, list):
        for level in levels:
            if not isinstance(level, dict):
                continue
            latency = level.get("latency_ms", {})
            if not isinstance(latency, dict):
                latency = {}
            lines.append(
                "| {concurrency} | {passed} | {failed} | {requests} | "
                "{throughput} | {p50} | {p95} | {p99} | {peak} | {model_peak} |".format(
                    concurrency=level.get("concurrency"),
                    passed=level.get("passed"),
                    failed=level.get("failed"),
                    requests=level.get("requests"),
                    throughput=level.get("throughput_cases_per_second"),
                    p50=latency.get("p50"),
                    p95=latency.get("p95"),
                    p99=latency.get("p99"),
                    peak=level.get("peak_users"),
                    model_peak=level.get("model_peak_concurrency"),
                )
            )
    lines.extend(
        [
            "",
            "说明：压测输入来自项目现有 100 个评测案例；每个案例映射到独立用户和独立订单，",
            "但所有用户共享同一个 FastAPI 应用、LangGraph、异步 SQLAlchemy 会话工厂和 "
            "SQLite 数据库，",
            "因此可以观察共享服务在并发下的行为。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 ServiceFlow 异步压力测试")
    parser.add_argument(
        "--level",
        type=int,
        nargs="+",
        default=list(DEFAULT_LEVELS),
        help="并发用户档位，默认：1 10 25 50 100",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parents[4] / "outputs" / "evaluation",
    )
    args = parser.parse_args()
    cases = load_eval_cases([DEFAULT_EVAL_PATH, COMPLEX_EVAL_PATH])
    report = asyncio.run(
        run_async_pressure_test(cases=cases, levels=tuple(args.level))
    )
    json_path, markdown_path = write_pressure_outputs(report, args.output)
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
