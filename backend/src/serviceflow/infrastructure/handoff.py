import re
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.infrastructure.authorization import Principal
from serviceflow.infrastructure.event_log import EventLog
from serviceflow.infrastructure.support_queue import HandoffRecord, SupportQueue

_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def redact_text(value: str) -> str:
    return _PHONE.sub("[REDACTED_PHONE]", _EMAIL.sub("[REDACTED_EMAIL]", value))


class HandoffService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        principal: Principal,
        reason_code: str,
        reason: str,
        session_id: str | None = None,
        case_id: str | None = None,
        trace_id: str | None = None,
        context: dict[str, object] | None = None,
    ) -> HandoffRecord:
        now = datetime.now(UTC)
        safe_reason = redact_text(reason)[:500]
        safe_context = _redact_mapping(context or {})
        record = HandoffRecord(
            id=f"HANDOFF-{uuid4().hex[:12].upper()}",
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            session_id=session_id,
            case_id=case_id,
            trace_id=trace_id,
            reason_code=reason_code,
            reason=safe_reason,
            customer_message="已转交人工客服，系统不会在信息不足时继续猜测或执行。",
            queue=(
                "risk_review"
                if reason_code in {"provider_unknown", "unauthorized"}
                else "after_sales"
            ),
            priority="high" if reason_code in {"provider_unknown", "unauthorized"} else "normal",
            status="open",
            context=safe_context,
            created_at=now,
        )
        await SupportQueue(self._session).create(record)
        await EventLog(self._session).append(
            event_type="handoff_created",
            tenant_id=principal.tenant_id,
            actor="system",
            session_id=session_id,
            case_id=case_id,
            trace_id=trace_id,
            payload={
                "handoff_id": record.id,
                "reason_code": reason_code,
                "queue": record.queue,
                "priority": record.priority,
            },
            at=now,
        )
        await self._session.commit()
        return record


def _redact_mapping(value: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        if key.lower() in {"email", "phone", "address", "name", "raw_input"}:
            result[key] = "[REDACTED]"
        else:
            result[key] = _redact_value(item)
    return result


def _redact_value(value: object) -> object:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return _redact_mapping(value)
    if isinstance(value, list | tuple):
        return [_redact_value(item) for item in value]
    return value
