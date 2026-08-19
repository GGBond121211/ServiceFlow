from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from serviceflow.agent.model import ModelResult
from serviceflow.evaluation.models import EvalCase
from serviceflow.evaluation.runner import run_evaluation
from serviceflow.infrastructure.database import Base


class RunnerFakeModel:
    def complete_json(self, *, system: str, user: str) -> ModelResult:
        responses: dict[str, dict[str, object]] = {
            "Cancel ORDER-EVAL": _intent("ORDER-EVAL", "cancel", "none"),
            "What is the status of ORDER-EVAL?": _intent("ORDER-EVAL", "query", "none"),
            "Cancel my order": _intent(None, "cancel", "none", ["order_id"]),
            "It is ORDER-EVAL": _intent("ORDER-EVAL", None, "none", ["requested_action"]),
            "Refund ORDER-HIGH": _intent("ORDER-HIGH", "refund", "quality"),
        }
        return ModelResult(
            content=responses[user],
            model="fake-runner-model",
            input_tokens=10,
            output_tokens=5,
        )


def test_runner_resets_cases_handles_clarification_and_resumes_approval(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'runner.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    cases = [
        _case(
            case_id="normal_cancel",
            order_id="ORDER-EVAL",
            status="paid",
            amount="199.00",
            delivered_days_ago=None,
            messages=["Cancel ORDER-EVAL"],
            intent="cancel",
            issue_type="none",
            policy_id="POL-CANCEL-01",
            decision="cancel",
            tools=["get_order", "cancel_order"],
            final_state={"order_status": "cancelled"},
        ),
        _case(
            case_id="normal_query_after_reset",
            order_id="ORDER-EVAL",
            status="paid",
            amount="199.00",
            delivered_days_ago=None,
            messages=["What is the status of ORDER-EVAL?"],
            intent="query",
            issue_type="none",
            policy_id="POL-QUERY-01",
            decision="explain_only",
            tools=["get_order"],
            final_state={"order_status": "paid"},
        ),
        _case(
            case_id="clarification_cancel",
            order_id="ORDER-EVAL",
            status="paid",
            amount="199.00",
            delivered_days_ago=None,
            messages=["Cancel my order", "It is ORDER-EVAL"],
            intent="cancel",
            issue_type="none",
            policy_id="POL-CANCEL-01",
            decision="cancel",
            tools=["get_order", "cancel_order"],
            final_state={"order_status": "cancelled"},
        ),
        _case(
            case_id="boundary_approval_approved",
            order_id="ORDER-HIGH",
            status="delivered",
            amount="899.00",
            delivered_days_ago=2,
            messages=["Refund ORDER-HIGH"],
            intent="refund",
            issue_type="quality",
            policy_id="POL-APPROVAL-01",
            decision="approval_required",
            tools=["get_order", "create_approval", "decide_approval"],
            final_state={
                "order_status": "refunded",
                "refund_status": "completed",
                "approval_status": "approved",
            },
        ),
    ]

    run = run_evaluation(
        cases=cases,
        model=RunnerFakeModel(),
        session_factory=factory,
        commit="test-commit",
    )

    assert run.summary.total_cases == 4
    assert run.summary.completed_cases == 4
    assert run.summary.outcome_accuracy == 1.0
    assert run.summary.final_state_accuracy == 1.0
    assert run.summary.clarification_completion_rate == 1.0
    assert run.cases[1].actual_final_state == {"order_status": "paid"}
    assert run.cases[2].clarification_correct is True
    assert run.cases[3].actual_final_state == {
        "order_status": "refunded",
        "refund_status": "completed",
        "approval_status": "approved",
    }
    assert run.cases[3].actual_tools[-1] == "decide_approval"
    engine.dispose()


def _intent(
    order_id: str | None,
    action: str | None,
    issue_type: str,
    missing_fields: list[str] | None = None,
) -> dict[str, object]:
    if missing_fields is None:
        missing_fields = []
    return {
        "order_id": order_id,
        "requested_action": action,
        "issue_type": issue_type,
        "issue_summary": "Evaluation request",
        "missing_fields": missing_fields,
    }


def _case(
    *,
    case_id: str,
    order_id: str,
    status: str,
    amount: str,
    delivered_days_ago: int | None,
    messages: list[str],
    intent: str,
    issue_type: str,
    policy_id: str,
    decision: str,
    tools: list[str],
    final_state: dict[str, str],
) -> EvalCase:
    return EvalCase.model_validate(
        {
            "id": case_id,
            "category": "normal_handling",
            "user_id": "USER-EVAL",
            "initial_state": {
                "order_id": order_id,
                "status": status,
                "total_amount": amount,
                "delivered_days_ago": delivered_days_ago,
            },
            "messages": messages,
            "expected": {
                "intent": intent,
                "issue_type": issue_type,
                "policy_id": policy_id,
                "decision": decision,
                "expected_tools": tools,
                "final_state": final_state,
            },
        }
    )
