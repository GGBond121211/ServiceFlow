from datetime import date
from pathlib import Path

import pytest

from serviceflow.infrastructure.policy_ingestion import load_policy_documents
from serviceflow.infrastructure.qdrant_policy_store import ExactPolicyStore, PolicyRetriever


def test_policy_fixture_has_regulatory_provenance() -> None:
    path = (
        Path(__file__).parents[3]
        / "experiments"
        / "policy_documents"
        / "serviceflow_policy_v2.jsonl"
    )
    documents = load_policy_documents(path)

    assert len(documents) >= 7
    assert all(document.source_type == "regulation" for document in documents)
    official_hosts = ("https://www.gov.cn/", "https://sjfg.samr.gov.cn/")
    assert all(document.source_url.startswith(official_hosts) for document in documents)
    assert all(document.source_hash for document in documents)


@pytest.mark.asyncio
async def test_policy_retriever_returns_citable_evidence() -> None:
    path = (
        Path(__file__).parents[3]
        / "experiments"
        / "policy_documents"
        / "serviceflow_policy_v2.jsonl"
    )
    retriever = PolicyRetriever(ExactPolicyStore(load_policy_documents(path)))

    evidence, backend, fallback = await retriever.retrieve(
        "签收后七日内退货退款应该退回哪里",
        tenant_id="tenant-a",
        region="CN",
        at=date(2026, 8, 1),
    )

    assert backend == "exact"
    assert fallback is None
    assert evidence
    assert evidence[0].document.source_locator
    assert evidence[0].document.version == "cn-regulation-2020-revision"


@pytest.mark.asyncio
async def test_policy_retriever_can_retrieve_quality_repair_boundary() -> None:
    path = (
        Path(__file__).parents[3]
        / "experiments"
        / "policy_documents"
        / "serviceflow_policy_v2.jsonl"
    )
    retriever = PolicyRetriever(ExactPolicyStore(load_policy_documents(path)))

    evidence, backend, fallback = await retriever.retrieve(
        "商品质量问题可以维修还是换货，三包是不是统一三十天",
        tenant_id="tenant-a",
        region="CN",
        at=date(2026, 8, 1),
    )

    policy_ids = {item.document.policy_id for item in evidence}
    assert backend == "exact"
    assert fallback is None
    assert {"CN-QUALITY-002", "CN-QUALITY-004", "CN-QUALITY-005"} <= policy_ids
