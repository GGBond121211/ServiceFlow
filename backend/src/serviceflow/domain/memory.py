from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class MemoryScope(StrEnum):
    USER = "user"
    SESSION = "session"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    id: str
    owner: str
    tenant_id: str
    user_id: str
    session_id: str | None
    scope: MemoryScope
    source: str
    content: dict[str, str]
    content_schema: dict[str, str]
    confidence: float
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    consent_status: str
    edit_status: str
    delete_status: str
    status: MemoryStatus = MemoryStatus.ACTIVE


def confirmed_preference(
    *,
    memory_id: str,
    tenant_id: str,
    user_id: str,
    session_id: str | None,
    content: dict[str, Any],
    confidence: float,
    at: datetime,
    expires_at: datetime | None,
) -> MemoryRecord:
    allowed = {"language", "tone", "notification_channel", "currency"}
    if not content or set(content) - allowed:
        raise ValueError("只允许保存低风险用户偏好")
    if not 0 <= confidence <= 1:
        raise ValueError("memory confidence 必须在 0 到 1 之间")
    normalized = {key: str(value) for key, value in content.items()}
    return MemoryRecord(
        id=memory_id,
        owner=f"user:{user_id}",
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        scope=MemoryScope.USER,
        source="user_explicit_confirmation",
        content=normalized,
        content_schema={key: "string" for key in normalized},
        confidence=confidence,
        created_at=at,
        updated_at=at,
        expires_at=expires_at,
        consent_status="confirmed",
        edit_status="editable",
        delete_status="deletable",
    )
