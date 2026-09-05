from datetime import date

import pytest

from serviceflow.domain.policy_documents import PolicyDocument
from serviceflow.infrastructure.qdrant_policy_store import ExactPolicyStore, PolicyRetriever


def doc(policy_id: str, content: str, **overrides: object) -> PolicyDocument:
    values: dict[str, object] = {
        "policy_id": policy_id,
        "version": "v1",
        "title": policy_id,
        "content": content,
        "tenant_id": None,
        "region": "CN",
        "effective_from": "2026-01-01",
        "effective_to": None,
        "source_type": "regulation",
        "source_title": "官方法规",
        "source_url": "https://example.test/policy",
        "source_locator": "条款",
    }
    values.update(overrides)
    return PolicyDocument.from_mapping(values)


@pytest.mark.asyncio
async def test_exact_retrieval_filters_expired_and_wrong_scope() -> None:
    store = ExactPolicyStore(
        (
            doc("CURRENT", "质量问题可以退货", region="CN"),
            doc("EXPIRED", "质量问题可以退货", effective_to="2026-06-30"),
            doc("OTHER-REGION", "质量问题可以退货", region="US"),
            doc("OTHER-TENANT", "质量问题可以退货", tenant_id="tenant-b"),
        )
    )

    result = await store.search(
        "质量问题退货",
        tenant_id="tenant-a",
        region="CN",
        at=date(2026, 8, 1),
        limit=5,
    )

    assert [item.document.policy_id for item in result] == ["CURRENT"]


@pytest.mark.asyncio
async def test_qdrant_failure_falls_back_to_exact_and_is_visible() -> None:
    class DownQdrant:
        async def search(self, *args: object, **kwargs: object) -> tuple[()]:
            raise ConnectionError("qdrant stopped")

    exact = ExactPolicyStore((doc("CURRENT", "质量问题可以退货"),))
    retriever = PolicyRetriever(exact, DownQdrant())  # type: ignore[arg-type]

    evidence, backend, reason = await retriever.retrieve(
        "质量问题退货",
        tenant_id="tenant-a",
        region="CN",
        at=date(2026, 8, 1),
    )

    assert evidence[0].document.policy_id == "CURRENT"
    assert backend == "exact_fallback"
    assert reason == "ConnectionError"
