import argparse
import asyncio
import json
import subprocess
from pathlib import Path

from serviceflow.agent.model import OpenAICompatibleModel
from serviceflow.evaluation.loader import DEFAULT_EVAL_PATH, load_eval_cases
from serviceflow.evaluation.report import write_evaluation_outputs
from serviceflow.evaluation.runner import run_evaluation
from serviceflow.evaluation.stress import (
    COMPLEX_EVAL_PATH,
    DEFAULT_LEVELS,
    run_async_pressure_test,
    write_pressure_outputs,
)
from serviceflow.infrastructure.database import (
    create_database_engine,
    create_database_schema,
    create_session_factory,
)
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.seed import seed_database


def main() -> None:
    asyncio.run(_main())


async def _main() -> None:
    parser = argparse.ArgumentParser(prog="serviceflow")
    parser.add_argument(
        "command",
        choices=("db-init", "seed", "show-order", "eval", "async-stress"),
    )
    parser.add_argument("order_id", nargs="?")
    parser.add_argument("--cases", type=Path, nargs="+", default=[DEFAULT_EVAL_PATH])
    parser.add_argument("--level", type=int, nargs="+", default=list(DEFAULT_LEVELS))
    parser.add_argument("--output-stem", default="serviceflow-v1")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parents[3] / "outputs" / "evaluation",
    )
    args = parser.parse_args()

    if args.command == "async-stress":
        cases = load_eval_cases([DEFAULT_EVAL_PATH, COMPLEX_EVAL_PATH])
        report = await run_async_pressure_test(
            cases=cases,
            levels=tuple(args.level),
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
        return

    engine = create_database_engine()
    if args.command == "db-init":
        await create_database_schema(engine)
    elif args.command == "seed":
        await create_database_schema(engine)
        async with create_session_factory(engine)() as session:
            await seed_database(session)
    elif args.command == "show-order":
        if args.order_id is None:
            parser.error("show-order 命令需要提供 ORDER_ID")
        async with create_session_factory(engine)() as session:
            order = await OrderRepository(session).get(args.order_id)
        if order is None:
            raise SystemExit("order_not_found")
        delivered_at = None
        if order.delivered_at is not None:
            delivered_at = order.delivered_at.isoformat()
        items = []
        for item in order.items:
            items.append(
                {
                    "id": item.id,
                    "product_name": item.product_name,
                    "quantity": item.quantity,
                }
            )
        print(
            json.dumps(
                {
                    "id": order.id,
                    "user_id": order.user_id,
                    "status": order.status.value,
                    "total_amount": str(order.total_amount),
                    "placed_at": order.placed_at.isoformat(),
                    "delivered_at": delivered_at,
                    "items": items,
                },
                ensure_ascii=False,
            )
        )
    elif args.command == "eval":
        run = await run_evaluation(
            cases=load_eval_cases(args.cases),
            model=OpenAICompatibleModel.from_env(),
            session_factory=create_session_factory(engine),
            commit=_git_commit(),
        )
        json_path, markdown_path = write_evaluation_outputs(
            run,
            args.output,
            stem=args.output_stem,
        )
        print(
            json.dumps(
                {
                    "results": str(json_path),
                    "report": str(markdown_path),
                    "summary": run.summary.model_dump(mode="json"),
                },
                ensure_ascii=False,
            )
        )
    await engine.dispose()


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return "unknown"
