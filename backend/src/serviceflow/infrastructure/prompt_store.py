import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from serviceflow.domain.prompts import PromptBinding, PromptRun, PromptStatus
from serviceflow.infrastructure.database import ensure_utc
from serviceflow.infrastructure.tables import (
    AIPromptReleaseRow,
    AIPromptRunRow,
    AIPromptTemplateRow,
    AIPromptVersionRow,
)


class PromptStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(
        self,
        *,
        template_id: str,
        name: str,
        scene_code: str,
        version_id: str,
        version: str,
        release_id: str,
        content: str,
        environment: str,
        tenant_id: str | None,
        at: datetime,
        change_reason: str,
        variables_schema: dict[str, str] | None = None,
    ) -> PromptBinding:
        if variables_schema is None:
            variables_schema = {"memory_ids": "list", "context_sections": "list"}
        template = await self._session.get(AIPromptTemplateRow, template_id)
        if template is None:
            template = AIPromptTemplateRow(
                id=template_id,
                name=name,
                scene_code=scene_code,
                prompt_type="structured_intent",
                status=PromptStatus.ACTIVE.value,
                created_at=at,
            )
            self._session.add(template)
        version_row = await self._session.get(AIPromptVersionRow, version_id)
        if version_row is None:
            version_row = AIPromptVersionRow(
                id=version_id,
                template_id=template_id,
                version=version,
                content=content,
                variables_schema=variables_schema,
                model_config={},
                created_by="serviceflow",
                change_reason=change_reason,
                created_at=at,
            )
            self._session.add(version_row)
        release = await self._session.get(AIPromptReleaseRow, release_id)
        if release is None:
            release = AIPromptReleaseRow(
                id=release_id,
                version_id=version_id,
                environment=environment,
                tenant_id=tenant_id,
                traffic_ratio=1,
                status=PromptStatus.ACTIVE.value,
                created_at=at,
            )
            self._session.add(release)
        await self._session.flush()
        return PromptBinding(
            template_id=template_id,
            template_name=name,
            version_id=version_id,
            version=version,
            release_id=release_id,
            content=content,
            environment=environment,
            tenant_id=tenant_id,
            variables_schema=variables_schema,
        )

    async def resolve(
        self,
        *,
        name: str,
        environment: str,
        tenant_id: str | None,
    ) -> PromptBinding | None:
        result = await self._session.execute(
            select(AIPromptTemplateRow, AIPromptVersionRow, AIPromptReleaseRow)
            .join(AIPromptVersionRow, AIPromptVersionRow.template_id == AIPromptTemplateRow.id)
            .join(AIPromptReleaseRow, AIPromptReleaseRow.version_id == AIPromptVersionRow.id)
            .where(
                AIPromptTemplateRow.name == name,
                AIPromptTemplateRow.status == PromptStatus.ACTIVE.value,
                AIPromptReleaseRow.environment == environment,
                AIPromptReleaseRow.status == PromptStatus.ACTIVE.value,
                (
                    AIPromptReleaseRow.tenant_id.is_(None)
                    | (AIPromptReleaseRow.tenant_id == tenant_id)
                ),
            )
            .order_by(AIPromptReleaseRow.tenant_id.desc())
        )
        row = result.first()
        if row is None:
            return None
        template, version, release = row
        return PromptBinding(
            template_id=template.id,
            template_name=template.name,
            version_id=version.id,
            version=version.version,
            release_id=release.id,
            content=version.content,
            environment=release.environment,
            tenant_id=release.tenant_id,
            variables_schema=dict(version.variables_schema or {}),
        )

    async def record_run(
        self,
        *,
        request_id: str,
        run_id: str | None,
        binding: PromptBinding,
        variables: dict[str, Any],
        at: datetime,
    ) -> PromptRun:
        _validate_variables(binding.variables_schema, variables)
        variables_json = json.dumps(variables, ensure_ascii=False, sort_keys=True, default=str)
        run = PromptRun(
            id=f"PRUN-{uuid4().hex[:20]}",
            request_id=request_id,
            run_id=run_id,
            binding=binding,
            variables_hash=hashlib.sha256(variables_json.encode()).hexdigest(),
            variables_summary=variables,
            model_version=None,
            policy_version=None,
            input_tokens=0,
            output_tokens=0,
            created_at=at,
        )
        self._session.add(
            AIPromptRunRow(
                id=run.id,
                request_id=run.request_id,
                run_id=run.run_id,
                template_id=binding.template_id,
                version_id=binding.version_id,
                release_id=binding.release_id,
                variables_hash=run.variables_hash,
                variables_summary=variables,
                created_at=at,
            )
        )
        await self._session.flush()
        return run

    async def finish_run(
        self,
        run_id: str,
        *,
        model_version: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        row = await self._session.get(AIPromptRunRow, run_id)
        if row is None:
            raise LookupError("prompt_run_not_found")
        row.model_version = model_version
        row.input_tokens = input_tokens
        row.output_tokens = output_tokens
        await self._session.flush()

    async def get_run(self, run_id: str) -> PromptRun | None:
        row = await self._session.get(AIPromptRunRow, run_id)
        if row is None:
            return None
        binding = PromptBinding(
            template_id=row.template_id,
            template_name="",
            version_id=row.version_id,
            version="",
            release_id=row.release_id,
            content="",
            environment="",
            tenant_id=None,
            variables_schema={},
        )
        return PromptRun(
            id=row.id,
            request_id=row.request_id,
            run_id=row.run_id,
            binding=binding,
            variables_hash=row.variables_hash,
            variables_summary=dict(row.variables_summary or {}),
            model_version=row.model_version,
            policy_version=row.policy_version,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            created_at=ensure_utc(row.created_at),
        )


def _validate_variables(schema: dict[str, str], variables: dict[str, Any]) -> None:
    missing = [name for name in schema if name not in variables]
    if missing:
        raise ValueError(f"Prompt 变量缺失：{', '.join(missing)}")
    for name, kind in schema.items():
        if kind == "list" and not isinstance(variables[name], list):
            raise ValueError(f"Prompt 变量 {name} 类型错误")
