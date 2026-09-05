from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from serviceflow.infrastructure.embedding_model import OpenAICompatibleEmbedding
from serviceflow.infrastructure.policy_ingestion import load_policy_documents
from serviceflow.infrastructure.qdrant_policy_store import QdrantPolicyStore


async def build_index(policy_path: Path, collection: str, qdrant_url: str) -> None:
    documents = load_policy_documents(policy_path)
    embedding = OpenAICompatibleEmbedding.from_environment()
    store = QdrantPolicyStore.from_url(
        qdrant_url,
        embedding=embedding,
        collection_name=collection,
        hnsw_m=16,
        hnsw_ef_construction=128,
        hnsw_ef_search=64,
        hnsw_full_scan_threshold=10,
        indexing_threshold=1,
    )
    started = time.perf_counter()
    await store.upsert(documents)
    result = {
        "scope": "complete_policy_index_build",
        "document_count": len(documents),
        "embedding_model": embedding.model,
        "embedding_dimension": embedding.dimension,
        "collection": collection,
        "hnsw": {"m": 16, "ef_construct": 128, "ef_search": 64},
        "upsert_latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "collection_info": await store.describe(),
        "evidence_boundary": "证明完整语料索引可建立，不代表检索质量或 HNSW 参数最优。",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy-path", type=Path, required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    args = parser.parse_args()
    asyncio.run(build_index(args.policy_path, args.collection, args.qdrant_url))


if __name__ == "__main__":
    main()
