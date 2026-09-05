from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from serviceflow.infrastructure.provider_errors import ProviderErrorClass, ProviderFailure


class ProviderStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    provider: str
    operation: str
    timeout_seconds: float
    request_id: str
    idempotency_key: str
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    provider: str
    operation: str
    request_id: str
    idempotency_key: str
    status: ProviderStatus
    provider_reference: str | None = None
    error_class: ProviderErrorClass | None = None


class ProviderAdapter(Protocol):
    name: str

    async def execute(self, request: ProviderRequest) -> ProviderResponse: ...

    async def query(self, provider_reference: str) -> ProviderResponse: ...


class ProviderRouter:
    def __init__(
        self,
        adapters: Sequence[ProviderAdapter],
        *,
        attempts_per_adapter: int = 2,
    ) -> None:
        if not adapters or attempts_per_adapter < 1:
            raise ValueError("Provider 和尝试次数必须为正")
        self._adapters = tuple(adapters)
        self._attempts = attempts_per_adapter

    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        last_failure: ProviderFailure | None = None
        for adapter in self._adapters:
            routed = ProviderRequest(
                provider=adapter.name,
                operation=request.operation,
                timeout_seconds=request.timeout_seconds,
                request_id=request.request_id,
                idempotency_key=request.idempotency_key,
                payload=request.payload,
            )
            for _ in range(self._attempts):
                try:
                    response = await adapter.execute(routed)
                    if (
                        response.request_id != routed.request_id
                        or response.idempotency_key != routed.idempotency_key
                        or response.operation != routed.operation
                    ):
                        return _failed(routed, ProviderErrorClass.VALIDATION)
                    return response
                except ProviderFailure as failure:
                    last_failure = failure
                    if not failure.error_class.retryable:
                        return _failed(routed, failure.error_class)
                    if failure.outcome_unknown:
                        return _unknown(routed, failure.error_class)
        assert last_failure is not None
        return _failed(request, last_failure.error_class)

    async def query(self, provider_reference: str) -> ProviderResponse:
        for adapter in self._adapters:
            try:
                return await adapter.query(provider_reference)
            except ProviderFailure as failure:
                if not failure.error_class.retryable:
                    raise
        raise ProviderFailure(ProviderErrorClass.SERVER_ERROR, "provider query exhausted")


class FakeProviderAdapter:
    def __init__(
        self,
        name: str,
        *,
        execute_script: Sequence[ProviderResponse | ProviderFailure],
        query_script: Sequence[ProviderResponse | ProviderFailure] = (),
    ) -> None:
        self.name = name
        self._execute_script = deque(execute_script)
        self._query_script = deque(query_script)
        self.execute_calls = 0
        self.query_calls = 0
        self.side_effect_keys: set[str] = set()

    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        self.execute_calls += 1
        if not self._execute_script:
            raise ProviderFailure(ProviderErrorClass.SERVER_ERROR, "fake script exhausted")
        item = self._execute_script.popleft()
        if isinstance(item, ProviderFailure):
            if item.outcome_unknown:
                self.side_effect_keys.add(request.idempotency_key)
            raise item
        if item.status in {
            ProviderStatus.PENDING,
            ProviderStatus.SUCCEEDED,
            ProviderStatus.UNKNOWN,
        }:
            self.side_effect_keys.add(request.idempotency_key)
        return item

    async def query(self, provider_reference: str) -> ProviderResponse:
        if not provider_reference:
            raise ProviderFailure(ProviderErrorClass.VALIDATION, "provider reference is empty")
        self.query_calls += 1
        if not self._query_script:
            raise ProviderFailure(ProviderErrorClass.SERVER_ERROR, "fake query exhausted")
        item = self._query_script.popleft()
        if isinstance(item, ProviderFailure):
            raise item
        return item


def _failed(request: ProviderRequest, error: ProviderErrorClass) -> ProviderResponse:
    return ProviderResponse(
        provider=request.provider,
        operation=request.operation,
        request_id=request.request_id,
        idempotency_key=request.idempotency_key,
        status=ProviderStatus.FAILED,
        error_class=error,
    )


def _unknown(request: ProviderRequest, error: ProviderErrorClass) -> ProviderResponse:
    return ProviderResponse(
        provider=request.provider,
        operation=request.operation,
        request_id=request.request_id,
        idempotency_key=request.idempotency_key,
        status=ProviderStatus.UNKNOWN,
        provider_reference=f"{request.provider}:{request.request_id}",
        error_class=error,
    )
