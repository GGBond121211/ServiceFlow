from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from serviceflow.agent.graph import build_service_graph
from serviceflow.agent.model import ModelResult
from serviceflow.domain.models import Order
from serviceflow.evaluation.loader import load_eval_cases
from serviceflow.infrastructure.database import Base
from serviceflow.infrastructure.repositories import OrderRepository
from serviceflow.infrastructure.tables import UserRow

REFERENCE_DATE = date(2026, 8, 1)


class CaseModel:
    def __init__(self, content: dict[str, object]) -> None:
        self._content = content

    def complete_json(self, *, system: str, user: str) -> ModelResult:
        return ModelResult(
            content=self._content,
            model="fake-eval-model",
            input_tokens=10,
            output_tokens=5,
        )


def test_ten_seed_cases_follow_frozen_policy_and_tools(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'seed-eval.db').as_posix()}")
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    for case in load_eval_cases()[:10]:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        with factory() as session:
            session.add(UserRow(id=case.user_id, display_name="评测用户"))
            state = case.initial_state
            if state.order_id is not None:
                assert state.status is not None and state.total_amount is not None
                delivered_at = None
                if state.delivered_days_ago is not None:
                    delivered_date = REFERENCE_DATE - timedelta(days=state.delivered_days_ago)
                    delivered_at = datetime.combine(delivered_date, time(hour=10), tzinfo=UTC)
                OrderRepository(session).add(
                    Order(
                        id=state.order_id,
                        user_id=case.user_id,
                        status=state.status,
                        total_amount=state.total_amount,
                        placed_at=datetime(2026, 7, 1, tzinfo=UTC),
                        delivered_at=delivered_at,
                    )
                )
            session.commit()

        message = case.messages[0]
        missing_fields = []
        if state.order_id is None:
            missing_fields.append("order_id")
        if case.expected.intent is None:
            missing_fields.append("requested_action")
        requested_action = None
        if case.expected.intent is not None:
            requested_action = case.expected.intent.value
        issue_type = "other"
        if case.expected.issue_type is not None:
            issue_type = case.expected.issue_type.value
        model = CaseModel(
            {
                "order_id": state.order_id,
                "requested_action": requested_action,
                "issue_type": issue_type,
                "issue_summary": message,
                "missing_fields": missing_fields,
            }
        )
        graph = build_service_graph(model=model, session_factory=factory)

        result = graph.invoke(
            {
                "thread_id": case.id,
                "user_id": case.user_id,
                "user_message": message,
                "reference_date": REFERENCE_DATE.isoformat(),
            }
        )

        actual_tools = []
        for event in result.get("tool_events", []):
            actual_tools.append(event["tool"])
        expected_final = case.expected.final_state.model_dump(mode="json", exclude_none=True)
        actual_final = dict(result.get("final_business_state", {}))
        if "order_status" in expected_final and "order_status" not in actual_final:
            with factory() as session:
                order_id = state.order_id
                if order_id is None:
                    order_id = ""
                saved_order = OrderRepository(session).get(order_id)
            if saved_order is not None:
                actual_final["order_status"] = saved_order.status.value
        assert result["policy_id"] == case.expected.policy_id, case.id
        assert result["decision"] == case.expected.decision, case.id
        assert actual_tools == list(case.expected.expected_tools), case.id
        assert actual_final == expected_final, case.id

    engine.dispose()
