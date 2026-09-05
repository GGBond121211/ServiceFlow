from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class GatewayRequestContext:
    tenant_id: str = "default"
    request_id: str | None = None
    session_id: str | None = None
    goal_id: str | None = None
    case_id: str | None = None
    operation_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None

    def headers(self) -> dict[str, str]:
        values = {
            "x-serviceflow-tenant-id": self.tenant_id,
            "x-serviceflow-request-id": self.request_id,
            "x-serviceflow-session-id": self.session_id,
            "x-serviceflow-goal-id": self.goal_id,
            "x-serviceflow-case-id": self.case_id,
            "x-serviceflow-operation-id": self.operation_id,
            "x-serviceflow-run-id": self.run_id,
        }
        return {key: value for key, value in values.items() if value is not None}

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> "GatewayRequestContext":
        tenant_id = headers.get("x-serviceflow-tenant-id")
        if not tenant_id:
            raise ValueError("x-serviceflow-tenant-id_required")
        return cls(
            tenant_id=tenant_id,
            request_id=headers.get("x-serviceflow-request-id"),
            session_id=headers.get("x-serviceflow-session-id"),
            goal_id=headers.get("x-serviceflow-goal-id"),
            case_id=headers.get("x-serviceflow-case-id"),
            operation_id=headers.get("x-serviceflow-operation-id"),
            run_id=headers.get("x-serviceflow-run-id"),
        )


_CURRENT = ContextVar("serviceflow_gateway_request_context", default=GatewayRequestContext())


def current_gateway_context() -> GatewayRequestContext:
    return _CURRENT.get()


@contextmanager
def bind_gateway_context(
    *,
    tenant_id: str | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    goal_id: str | None = None,
    case_id: str | None = None,
    operation_id: str | None = None,
    run_id: str | None = None,
    trace_id: str | None = None,
) -> Iterator[GatewayRequestContext]:
    current = current_gateway_context()
    updates = {
        key: value
        for key, value in {
            "tenant_id": tenant_id,
            "request_id": request_id,
            "session_id": session_id,
            "goal_id": goal_id,
            "case_id": case_id,
            "operation_id": operation_id,
            "run_id": run_id,
            "trace_id": trace_id,
        }.items()
        if value is not None
    }
    bound = replace(current, **updates)
    token = _CURRENT.set(bound)
    try:
        yield bound
    finally:
        _CURRENT.reset(token)
