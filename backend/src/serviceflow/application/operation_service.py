from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from serviceflow.application.session_service import SessionService
from serviceflow.domain.operations import ActionType, ErrorClass, Operation, OperationStatus
from serviceflow.infrastructure.authorization import Authorization, Principal
from serviceflow.infrastructure.case_repository import AfterSalesCaseStore, OperationStore
from serviceflow.infrastructure.event_log import EventLog
from serviceflow.infrastructure.idempotency import stable_action_id
from serviceflow.infrastructure.outbox import Outbox
from serviceflow.infrastructure.provider_adapters import (
    ProviderRequest,
    ProviderResponse,
    ProviderRouter,
    ProviderStatus,
)
from serviceflow.infrastructure.provider_errors import ProviderErrorClass
from serviceflow.infrastructure.task_queue import TaskEnvelope, TaskQueue, TaskStatus


@dataclass(frozen=True, slots=True)
class OperationLookup:
    code: str
    operation: Operation | None = None


class OperationService:
    def __init__(self, session: AsyncSession, *, tenant_id: str) -> None:
        self._operations = OperationStore(session)
        self._cases = AfterSalesCaseStore(session)
        self._authorization = Authorization(tenant_id)

    async def get(self, operation_id: str, principal: Principal) -> OperationLookup:
        operation = await self._operations.get(operation_id)
        if operation is None:
            return OperationLookup("not_found")
        case = await self._cases.get(operation.case_id)
        if case is None or not self._authorization.case_allowed(principal, case):
            return OperationLookup("unauthorized")
        return OperationLookup("ok", operation)


@dataclass(frozen=True, slots=True)
class ProviderOperationResult:
    operation: Operation
    provider_response: ProviderResponse | None
    replay_code: str


class ProviderOperationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        router: ProviderRouter,
    ) -> None:
        self._session_factory = session_factory
        self._sessions = SessionService(session_factory)
        self._router = router

    async def dispatch(
        self,
        *,
        case_id: str,
        action_type: ActionType,
        provider: str,
        operation_name: str,
        request_id: str,
        payload: dict[str, object],
        run_id: str,
        session_id: str,
        traceparent: str,
        timeout_seconds: float = 5.0,
    ) -> ProviderOperationResult:
        action_id = stable_action_id(
            request_id=request_id,
            operation=operation_name,
            subject_id=case_id,
        )
        begin = await self._sessions.begin_operation(
            case_id=case_id,
            action_type=action_type,
            action_id=action_id,
            payload=payload,
            trace_id=_trace_id(traceparent),
        )
        if not begin.may_execute:
            return ProviderOperationResult(begin.operation, None, begin.verdict.value)
        request = ProviderRequest(
            provider=provider,
            operation=operation_name,
            timeout_seconds=timeout_seconds,
            request_id=request_id,
            idempotency_key=action_id,
            payload=payload,
        )
        response = await self._router.execute(request)
        operation = await self._record_provider_response(
            operation=begin.operation,
            response=response,
            run_id=run_id,
            session_id=session_id,
            traceparent=traceparent,
        )
        return ProviderOperationResult(operation, response, begin.verdict.value)

    async def reconcile(
        self,
        *,
        operation_id: str,
        traceparent: str,
    ) -> Operation:
        async with self._session_factory() as db:
            current = await OperationStore(db).get(operation_id)
        if current is None:
            raise LookupError("operation_not_found")
        if current.status not in {OperationStatus.PENDING, OperationStatus.UNKNOWN}:
            return current
        if current.provider_ref is None:
            raise LookupError("provider_reference_missing")
        response = await self._router.query(current.provider_ref)
        async with self._session_factory() as db:
            operation = await OperationStore(db).finish(
                operation_id,
                status=_operation_status(response.status),
                at=datetime.now(UTC),
                result_code=response.status.value,
                error_class=_error_class(response.error_class),
                provider_ref=response.provider_reference or current.provider_ref,
            )
            if response.status is ProviderStatus.SUCCEEDED:
                await _enqueue_completion(db, operation, traceparent)
            await _append_provider_event(db, operation, response, traceparent)
            await db.commit()
        return operation

    async def _record_provider_response(
        self,
        *,
        operation: Operation,
        response: ProviderResponse,
        run_id: str,
        session_id: str,
        traceparent: str,
    ) -> Operation:
        now = datetime.now(UTC)
        async with self._session_factory() as db:
            updated = await OperationStore(db).finish(
                operation.id,
                status=_operation_status(response.status),
                at=now,
                result_code=response.status.value,
                error_class=_error_class(response.error_class),
                provider_ref=response.provider_reference,
            )
            if response.status is ProviderStatus.SUCCEEDED:
                await _enqueue_completion(db, updated, traceparent)
            if response.status in {ProviderStatus.PENDING, ProviderStatus.UNKNOWN}:
                await TaskQueue(db).enqueue(
                    TaskEnvelope(
                        id=f"TASK-{updated.id}",
                        run_id=run_id,
                        session_id=session_id,
                        case_id=updated.case_id,
                        operation_id=updated.id,
                        idempotency_key=updated.action_id,
                        task_type="provider_reconcile",
                        payload={"provider_reference": updated.provider_ref or ""},
                        attempt=0,
                        max_attempts=3,
                        deadline=now + timedelta(minutes=5),
                        status=TaskStatus.QUEUED,
                        error_class="none",
                        available_at=now,
                        traceparent=traceparent,
                        created_at=now,
                        updated_at=now,
                    )
                )
            await _append_provider_event(db, updated, response, traceparent)
            await db.commit()
        return updated


async def _enqueue_completion(
    db: AsyncSession,
    operation: Operation,
    traceparent: str,
) -> None:
    await Outbox(db).enqueue(
        dedupe_key=f"operation-completed:{operation.id}",
        aggregate_type="operation",
        aggregate_id=operation.id,
        event_type="operation_completed",
        payload={"operation_id": operation.id, "result_code": operation.result_code},
        traceparent=traceparent,
    )


async def _append_provider_event(
    db: AsyncSession,
    operation: Operation,
    response: ProviderResponse,
    traceparent: str,
) -> None:
    case = await AfterSalesCaseStore(db).get(operation.case_id)
    await EventLog(db).append(
        event_type="provider_operation_updated",
        tenant_id=case.tenant_id if case else "unknown",
        actor="provider",
        goal_id=case.goal_id if case else None,
        case_id=operation.case_id,
        operation_id=operation.id,
        trace_id=_trace_id(traceparent),
        payload={
            "provider": response.provider,
            "status": response.status.value,
            "error_class": response.error_class.value if response.error_class else "none",
        },
    )


def _operation_status(status: ProviderStatus) -> OperationStatus:
    return {
        ProviderStatus.PENDING: OperationStatus.PENDING,
        ProviderStatus.SUCCEEDED: OperationStatus.SUCCEEDED,
        ProviderStatus.FAILED: OperationStatus.FAILED,
        ProviderStatus.UNKNOWN: OperationStatus.UNKNOWN,
    }[status]


def _error_class(error: ProviderErrorClass | None) -> ErrorClass:
    if error is None:
        return ErrorClass.NONE
    if error is ProviderErrorClass.TIMEOUT:
        return ErrorClass.TIMEOUT
    if error in {ProviderErrorClass.AUTHENTICATION, ProviderErrorClass.PERMISSION}:
        return ErrorClass.CONFLICT
    if error in {ProviderErrorClass.VALIDATION, ProviderErrorClass.POLICY}:
        return ErrorClass.VALIDATION
    return ErrorClass.PROVIDER_ERROR


def _trace_id(traceparent: str) -> str:
    return traceparent.split("-")[1]
