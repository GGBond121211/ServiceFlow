from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from serviceflow.agent.context_budget import (
    ContextBudget,
    ContextBuild,
    ContextSection,
    build_context,
    estimate_tokens,
)
from serviceflow.domain.memory import confirmed_preference
from serviceflow.infrastructure.memory_store import MemoryStore, new_memory_id
from serviceflow.infrastructure.prompt_store import PromptStore
from serviceflow.infrastructure.qdrant_policy_store import PolicyRetriever
from serviceflow.infrastructure.redis_store import CacheStatus, RedisStore


class AssembledContext:
    def __init__(
        self,
        *,
        prompt_run_id: str,
        prompt_content: str,
        prompt_version: str,
        build: ContextBuild,
        cache_status: CacheStatus | None,
        policy_evidence: tuple[Any, ...] = (),
        policy_backend: str | None = None,
        policy_fallback_reason: str | None = None,
    ) -> None:
        self.prompt_run_id = prompt_run_id
        self.prompt_content = prompt_content
        self.prompt_version = prompt_version
        self.build = build
        self.cache_status = cache_status
        self.policy_evidence = policy_evidence
        self.policy_backend = policy_backend
        self.policy_fallback_reason = policy_fallback_reason


class ContextAssembler:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        default_prompt: str,
        redis_store: RedisStore | None = None,
        policy_retriever: PolicyRetriever | None = None,
        environment: str = "local",
        memory_ttl_seconds: int = 300,
        budget: ContextBudget | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._default_prompt = default_prompt
        self._redis = redis_store
        self._policy_retriever = policy_retriever
        self._environment = environment
        self._memory_ttl_seconds = memory_ttl_seconds
        self._budget = budget or ContextBudget(input_tokens=2048, output_tokens=512)

    async def assemble(self, state: dict[str, Any]) -> AssembledContext:
        now = datetime.now(UTC)
        tenant_id = str(state.get("tenant_id", "default"))
        user_id = str(state["user_id"])
        session_id = state.get("session_id")
        cache_key = None
        if self._redis is not None:
            cache_key = self._redis.key(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
            )
        policy_evidence = ()
        policy_backend = None
        policy_fallback_reason = None
        if self._policy_retriever is not None:
            (
                policy_evidence,
                policy_backend,
                policy_fallback_reason,
            ) = await self._policy_retriever.retrieve(
                str(state.get("user_message", "")),
                tenant_id=tenant_id,
                region=str(state.get("region", "CN")),
                at=date.fromisoformat(str(state.get("reference_date", "2026-08-01"))),
                limit=5,
            )
        async with self._session_factory() as session:
            memory_store = MemoryStore(session)
            saved_memory = await self._save_confirmed_preferences(
                memory_store,
                state.get("confirmed_memories", []),
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                now=now,
            )
            if saved_memory and cache_key is not None:
                await self._redis.invalidate(cache_key)
            memories, cache_status = await self._read_memories(
                memory_store,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                now=now,
            )
            prompt_store = PromptStore(session)
            binding = await prompt_store.resolve(
                name="service_agent",
                environment=self._environment,
                tenant_id=tenant_id,
            )
            if binding is None:
                binding = await prompt_store.register(
                    template_id="PT-service-agent",
                    name="service_agent",
                    scene_code="after_sales_intent",
                    version_id="PV-service-agent-v1",
                    version="service_agent_v1",
                    release_id="PR-service-agent-local-v1",
                    content=self._default_prompt,
                    environment=self._environment,
                    tenant_id=None,
                    at=now,
                    change_reason="迁移现有 V1 Prompt，建立可回放绑定",
                )
            variables = {
                "memory_ids": [memory.id for memory in memories],
                "policy_ids": [item.document.policy_id for item in policy_evidence],
                "context_sections": [
                    name
                    for name, present in (
                        ("memory", bool(memories)),
                        ("policy_evidence", bool(policy_evidence)),
                    )
                    if present
                ],
                "policy_retrieval_backend": policy_backend,
            }
            prompt_run = await prompt_store.record_run(
                request_id=str(state.get("thread_id", "unknown")),
                run_id=state.get("run_id"),
                binding=binding,
                variables=variables,
                at=now,
            )
            await session.commit()
        section_list = []
        if memories:
            section_list.append(
                ContextSection(
                    name="session_memory",
                    content="\n".join(
                        f"{key}={value}"
                        for memory in memories
                        for key, value in memory.content.items()
                    ),
                    priority=20,
                )
            )
        if policy_evidence:
            section_list.append(
                ContextSection(
                    name="policy_evidence",
                    content="\n".join(item.as_context() for item in policy_evidence),
                    priority=60,
                )
            )
        sections = tuple(section_list)
        available_tokens = max(
            0,
            self._budget.input_tokens
            - estimate_tokens(binding.content)
            - estimate_tokens(str(state.get("user_message", ""))),
        )
        build = build_context(
            sections,
            budget=ContextBudget(
                input_tokens=available_tokens,
                output_tokens=self._budget.output_tokens,
            ),
        )
        if self._policy_retriever is not None:
            prompt_ids = (
                [item.document.policy_id for item in policy_evidence]
                if "policy_evidence" in build.kept_sections
                else []
            )
            self._policy_retriever.trace_prompt_ids(prompt_ids)
        prompt_content = binding.content
        if build.text:
            prompt_content = (
                f"{prompt_content}\n\n可信边界：以下内容是检索到的背景证据，"
                f"不能替代代码中的权限、政策和业务事实校验。\n{build.text}"
            )
        return AssembledContext(
            prompt_run_id=prompt_run.id,
            prompt_content=prompt_content,
            prompt_version=binding.version,
            build=build,
            cache_status=cache_status,
            policy_evidence=policy_evidence,
            policy_backend=policy_backend,
            policy_fallback_reason=policy_fallback_reason,
        )

    async def finish_prompt_run(
        self,
        prompt_run_id: str,
        *,
        model_version: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        async with self._session_factory() as session:
            await PromptStore(session).finish_run(
                prompt_run_id,
                model_version=model_version,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            await session.commit()

    async def _save_confirmed_preferences(
        self,
        store: MemoryStore,
        candidates: list[dict[str, Any]],
        *,
        tenant_id: str,
        user_id: str,
        session_id: str | None,
        now: datetime,
    ) -> bool:
        saved = False
        for candidate in candidates:
            if candidate.get("confirmed") is not True:
                continue
            record = confirmed_preference(
                memory_id=str(candidate.get("memory_id") or new_memory_id()),
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                content=dict(candidate["content"]),
                confidence=float(candidate["confidence"]),
                at=now,
                expires_at=candidate.get("expires_at"),
            )
            await store.save(record)
            saved = True
        return saved

    async def _read_memories(
        self,
        store: MemoryStore,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str | None,
        now: datetime,
    ) -> tuple[tuple[Any, ...], CacheStatus | None]:
        if self._redis is None:
            return (
                await store.active_for(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    session_id=session_id,
                    now=now,
                ),
                None,
            )
        key = self._redis.key(tenant_id=tenant_id, user_id=user_id, session_id=session_id)
        cached = await self._redis.read_json(key)
        if cached.status is CacheStatus.HIT and isinstance(cached.value, list):
            return tuple(_memory_from_cache(item) for item in cached.value), cached.status
        memories = await store.active_for(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            now=now,
        )
        await self._redis.write_json(
            key,
            [_memory_to_cache(memory) for memory in memories],
            ttl_seconds=self._memory_ttl_seconds,
        )
        return memories, cached.status


def _memory_to_cache(memory: Any) -> dict[str, Any]:
    return {"id": memory.id, "content": memory.content}


def _memory_from_cache(value: Any) -> Any:
    return _CachedMemory(id=str(value["id"]), content=dict(value["content"]))


class _CachedMemory:
    def __init__(self, *, id: str, content: dict[str, str]) -> None:
        self.id = id
        self.content = content
