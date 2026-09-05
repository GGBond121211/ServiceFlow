import json
from datetime import date
from pathlib import Path

import pytest

from serviceflow.infrastructure.policy_ingestion import load_policy_documents
from serviceflow.infrastructure.qdrant_policy_store import ExactPolicyStore

QUERY_PATH = (
    Path(__file__).parents[3]
    / "experiments"
    / "policy_documents"
    / "step4_retrieval_queries.jsonl"
)
POLICY_PATH = QUERY_PATH.with_name("serviceflow_policy_v2.jsonl")


def load_queries() -> list[dict[str, object]]:
    return [json.loads(line) for line in QUERY_PATH.read_text(encoding="utf-8").splitlines()]


def test_policy_query_manifest_covers_required_boundaries() -> None:
    queries = load_queries()
    query_ids = {str(query["query_id"]) for query in queries}

    assert len(queries) >= 8
    assert len(query_ids) == len(queries)
    assert {"wrong_region_us", "before_policy_effective_date"} <= query_ids
    assert "policy_identifier_gap_probe" in query_ids
    assert all("tenant_id" in query and "region" in query for query in queries)


@pytest.mark.asyncio
async def test_exact_baseline_matches_active_quality_boundaries() -> None:
    store = ExactPolicyStore(load_policy_documents(POLICY_PATH))
    query = next(
        item for item in load_queries() if item["query_id"] == "quality_repair_exchange_cn"
    )

    evidence = await store.search(
        str(query["query"]),
        tenant_id=str(query["tenant_id"]),
        region=str(query["region"]),
        at=date.fromisoformat(str(query["at"])),
        limit=5,
    )

    policy_ids = {item.document.policy_id for item in evidence}
    assert {"CN-QUALITY-002", "CN-QUALITY-004"} <= policy_ids


@pytest.mark.asyncio
async def test_exact_baseline_excludes_wrong_region_and_not_yet_effective_policy() -> None:
    store = ExactPolicyStore(load_policy_documents(POLICY_PATH))
    cases = [
        next(item for item in load_queries() if item["query_id"] == "wrong_region_us"),
        next(item for item in load_queries() if item["query_id"] == "before_policy_effective_date"),
    ]

    wrong_region = cases[0]
    evidence = await store.search(
        str(wrong_region["query"]),
        tenant_id=str(wrong_region["tenant_id"]),
        region=str(wrong_region["region"]),
        at=date.fromisoformat(str(wrong_region["at"])),
        limit=5,
    )
    assert evidence == ()

    before_seven_day_policy = cases[1]
    evidence = await store.search(
        str(before_seven_day_policy["query"]),
        tenant_id=str(before_seven_day_policy["tenant_id"]),
        region=str(before_seven_day_policy["region"]),
        at=date.fromisoformat(str(before_seven_day_policy["at"])),
        limit=5,
    )
    policy_ids = {item.document.policy_id for item in evidence}
    assert {"CN-7DAY-001", "CN-7DAY-002", "CN-7DAY-003"}.isdisjoint(policy_ids)
