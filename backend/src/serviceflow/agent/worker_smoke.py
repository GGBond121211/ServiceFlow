import argparse
import asyncio
import json
from uuid import uuid4

from serviceflow.agent.worker_tasks import celery_app
from serviceflow.api.dependencies import SessionFactory, engine
from serviceflow.application.operation_service import ProviderOperationService
from serviceflow.application.session_service import SessionService
from serviceflow.domain.cases import CaseType
from serviceflow.domain.operations import ActionType
from serviceflow.domain.sessions import Channel
from serviceflow.infrastructure.idempotency import stable_action_id
from serviceflow.infrastructure.outbox import Outbox
from serviceflow.infrastructure.provider_adapters import (
    FakeProviderAdapter,
    ProviderResponse,
    ProviderRouter,
    ProviderStatus,
)
from serviceflow.infrastructure.provider_event_inbox import (
    ProviderEvent,
    ProviderEventProcessor,
)


async def _enqueue() -> dict[str, str]:
    token = uuid4().hex
    traceparent = f"00-{token}-{token[:16]}-01"
    async with SessionFactory() as session:
        message = await Outbox(session).enqueue(
            dedupe_key=f"worker-smoke:{token}",
            aggregate_type="smoke",
            aggregate_id=f"SMOKE-{token[:12].upper()}",
            event_type="worker_smoke_requested",
            payload={"token": token},
            traceparent=traceparent,
        )
        await session.commit()
    task = celery_app.send_task("serviceflow.deliver_outbox", args=[message.id])
    return {"message_id": message.id, "task_id": task.id, "traceparent": traceparent}


async def _provider() -> dict[str, object]:
    token = uuid4().hex
    request_id = f"REQ-{token[:12].upper()}"
    traceparent = f"00-{token}-{token[:16]}-01"
    sessions = SessionService(SessionFactory)
    conversation = await sessions.start_session(
        tenant_id="smoke",
        user_id=f"USER-{token[:8].upper()}",
        channel=Channel.EVAL,
    )
    goal = await sessions.open_goal(
        session_id=conversation.id,
        order_id=f"ORDER-{token[:8].upper()}",
        scene_code="refund",
        created_by="step7-smoke",
    )
    case = await sessions.open_case(
        goal_id=goal.id,
        order_id=goal.order_id,
        case_type=CaseType.REFUND,
        reason="Step 7 Provider/Webhook smoke",
    )
    action_id = stable_action_id(
        request_id=request_id,
        operation="refund",
        subject_id=case.id,
    )
    adapter = FakeProviderAdapter(
        "fake-refund",
        execute_script=[
            ProviderResponse(
                provider="fake-refund",
                operation="refund",
                request_id=request_id,
                idempotency_key=action_id,
                status=ProviderStatus.PENDING,
                provider_reference=f"FAKE-{token[:12].upper()}",
            )
        ],
    )
    dispatched = await ProviderOperationService(
        SessionFactory, ProviderRouter([adapter])
    ).dispatch(
        case_id=case.id,
        action_type=ActionType.REFUND,
        provider=adapter.name,
        operation_name="refund",
        request_id=request_id,
        payload={"order_id": goal.order_id, "amount": "199.00"},
        run_id=f"RUN-{token[:12].upper()}",
        session_id=conversation.id,
        traceparent=traceparent,
    )
    event = ProviderEvent(
        provider=adapter.name,
        event_id=f"EVENT-{token[:12].upper()}",
        event_type="refund.completed",
        operation_id=dispatched.operation.id,
        payload={"provider_reference": dispatched.operation.provider_ref or ""},
        traceparent=traceparent,
    )
    processor = ProviderEventProcessor(SessionFactory)
    first = await processor.apply(event, ProviderStatus.SUCCEEDED)
    duplicate = await processor.apply(event, ProviderStatus.SUCCEEDED)
    return {
        "operation_id": dispatched.operation.id,
        "dispatched_status": dispatched.operation.status.value,
        "execute_calls": adapter.execute_calls,
        "first_webhook_applied": first,
        "duplicate_webhook_applied": duplicate,
        "traceparent": traceparent,
    }


async def _run_database_command(command: str) -> dict[str, object]:
    try:
        return await (_enqueue() if command == "enqueue" else _provider())
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="ServiceFlow Celery/Redis/Outbox 本地烟测")
    parser.add_argument("command", choices=("enqueue", "provider", "wait"))
    parser.add_argument("task_id", nargs="?")
    arguments = parser.parse_args()
    if arguments.command in {"enqueue", "provider"}:
        result = asyncio.run(_run_database_command(arguments.command))
    else:
        if not arguments.task_id:
            parser.error("wait 需要 task_id")
        result = celery_app.AsyncResult(arguments.task_id).get(timeout=60)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
