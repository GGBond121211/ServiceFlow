from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class PromptStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class PromptBinding:
    template_id: str
    template_name: str
    version_id: str
    version: str
    release_id: str
    content: str
    environment: str
    tenant_id: str | None
    variables_schema: dict[str, str]


@dataclass(frozen=True, slots=True)
class PromptRun:
    id: str
    request_id: str
    run_id: str | None
    binding: PromptBinding
    variables_hash: str
    variables_summary: dict[str, Any]
    model_version: str | None
    policy_version: str | None
    input_tokens: int
    output_tokens: int
    created_at: datetime
