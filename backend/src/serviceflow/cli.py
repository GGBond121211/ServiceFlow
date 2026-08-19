import argparse
import json
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from serviceflow.agent.model import OpenAICompatibleModel
from serviceflow.evaluation.loader import DEFAULT_EVAL_PATH, load_eval_cases
from serviceflow.evaluation.report import write_evaluation_outputs
from serviceflow.evaluation.runner import run_evaluation
from serviceflow.infrastructure.database import (
    Base,
    create_database_engine,
    create_session_factory,
)
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.seed import seed_database


def main() -> None:
    parser = argparse.ArgumentParser(prog="serviceflow")
    parser.add_argument("command", choices=("db-init", "seed", "show-order", "eval"))
    parser.add_argument("order_id", nargs="?")
    parser.add_argument("--cases", type=Path, nargs="+", default=[DEFAULT_EVAL_PATH])
    parser.add_argument("--output-stem", default="serviceflow-v1")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parents[3] / "outputs" / "evaluation",
    )
    args = parser.parse_args()

    engine = create_database_engine()
    if args.command == "db-init":
        Base.metadata.create_all(engine)
    elif args.command == "seed":
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            seed_database(session)
    elif args.command == "show-order":
        if args.order_id is None:
            parser.error("show-order 命令需要提供 ORDER_ID")
        with Session(engine) as session:
            order = OrderRepository(session).get(args.order_id)
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
        run = run_evaluation(
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
    engine.dispose()


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
