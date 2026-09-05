from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from typing import Any


@dataclass(frozen=True, slots=True)
class PolicyDocument:
    policy_id: str
    version: str
    title: str
    content: str
    tenant_id: str | None
    region: str | None
    effective_from: date
    effective_to: date | None
    source_type: str
    source_title: str
    source_url: str
    source_locator: str
    source_hash: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "PolicyDocument":
        content = str(value["content"])
        source_url = str(value["source_url"])
        source_locator = str(value["source_locator"])
        source_hash = str(
            value.get("source_hash")
            or sha256(f"{source_url}\n{source_locator}\n{content}".encode()).hexdigest()
        )
        return cls(
            policy_id=str(value["policy_id"]),
            version=str(value["version"]),
            title=str(value["title"]),
            content=content,
            tenant_id=_optional_text(value.get("tenant_id")),
            region=_optional_text(value.get("region")),
            effective_from=date.fromisoformat(str(value["effective_from"])),
            effective_to=(
                date.fromisoformat(str(value["effective_to"]))
                if value.get("effective_to")
                else None
            ),
            source_type=str(value["source_type"]),
            source_title=str(value["source_title"]),
            source_url=source_url,
            source_locator=source_locator,
            source_hash=source_hash,
        )

    def applies_to(self, *, tenant_id: str, region: str, at: date) -> bool:
        tenant_matches = self.tenant_id is None or self.tenant_id == tenant_id
        region_matches = self.region is None or self.region == region
        date_matches = self.effective_from <= at and (
            self.effective_to is None or at <= self.effective_to
        )
        return tenant_matches and region_matches and date_matches


@dataclass(frozen=True, slots=True)
class PolicyEvidence:
    document: PolicyDocument
    score: float
    rank: int

    def as_context(self) -> str:
        document = self.document
        end = document.effective_to.isoformat() if document.effective_to else "持续有效"
        return (
            f"{document.policy_id} | {document.version} | {document.title} | "
            f"有效期 {document.effective_from.isoformat()} 至 {end} | "
            f"来源 {document.source_title} {document.source_locator} | {document.content}"
        )


def _optional_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)
