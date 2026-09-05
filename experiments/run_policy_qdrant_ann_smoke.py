from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from serviceflow.infrastructure.embedding_model import OpenAICompatibleEmbedding  # noqa: E402
from serviceflow.infrastructure.policy_ingestion import load_policy_documents  # noqa: E402
from serviceflow.infrastructure.qdrant_policy_store import QdrantPolicyStore  # noqa: E402

POLICY_PATH = ROOT / "experiments" / "policy_documents" / "serviceflow_policy_v2_expanded.jsonl"
QUERY_PATH = ROOT / "experiments" / "policy_documents" / "step4_retrieval_queries_v2.jsonl"


async def main(output: Path | None) -> None:
    documents = load_policy_documents(POLICY_PATH)
    all_queries = [json.loads(line) for line in QUERY_PATH.read_text(encoding="utf-8").splitlines()]
    selected_ids = {"v2_return_window_plain", "v2_quality_freight", "v2_wrong_region"}
    queries = [query for query in all_queries if query["query_id"] in selected_ids]
    embedding = OpenAICompatibleEmbedding.from_environment()
    store = QdrantPolicyStore.from_url(
        "http://127.0.0.1:6333",
        embedding=embedding,
        collection_name="serviceflow_policy_v2_qwen3_7_text_embedding_hnsw_forced_smoke_v3",
        hnsw_m=16,
        hnsw_ef_construction=128,
        hnsw_ef_search=64,
        hnsw_full_scan_threshold=10,
        indexing_threshold=1,
    )
    started = time.perf_counter()
    await store.upsert(documents)
    upsert_ms = (time.perf_counter() - started) * 1000
    collection_info = await store.describe()
    cases = []
    for query in queries:
        started = time.perf_counter()
        evidence = await store.search(
            query["query"],
            tenant_id=query["tenant_id"],
            region=query["region"],
            at=date.fromisoformat(query["at"]),
            limit=5,
        )
        cases.append(
            {
                "query_id": query["query_id"],
                "expected_policy_ids": query["expected_policy_ids"],
                "policy_ids": [item.document.policy_id for item in evidence],
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        )
    result = {
        "methodology": {
            "live_embedding": True,
            "document_count": len(documents),
            "query_count": len(queries),
            "qdrant_url": "http://127.0.0.1:6333",
            "collection": "serviceflow_policy_v2_qwen3_7_text_embedding_hnsw_forced_smoke_v3",
            "ann": "Qdrant HNSW",
            "hnsw_m": 16,
            "hnsw_ef_construction": 128,
            "hnsw_ef_search": 64,
            "hnsw_full_scan_threshold": 10,
            "indexing_threshold": 1,
            "embedding_model": embedding.model,
            "embedding_dimension": embedding.dimension,
            "upsert_latency_ms": round(upsert_ms, 3),
            "scope": "ANN smoke only; three representative queries, not a quality conclusion.",
            "collection_info": collection_info,
        },
        "cases": cases,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"result_written={output}")
    else:
        print(rendered)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    asyncio.run(main(args.output))
