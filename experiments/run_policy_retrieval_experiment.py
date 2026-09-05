from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from serviceflow.infrastructure.embedding_model import OpenAICompatibleEmbedding  # noqa: E402
from serviceflow.infrastructure.policy_ingestion import load_policy_documents  # noqa: E402
from serviceflow.infrastructure.policy_retrieval import (  # noqa: E402
    InMemorySemanticPolicyStore,
    PolicyBM25,
    RankedPolicy,
    fuse_policy_results,
)
from serviceflow.infrastructure.qdrant_policy_store import ExactPolicyStore  # noqa: E402

POLICY_PATH = ROOT / "experiments" / "policy_documents" / "serviceflow_policy_v2_expanded.jsonl"
QUERY_PATH = ROOT / "experiments" / "policy_documents" / "step4_retrieval_queries_v2.jsonl"


def load_queries(split: str | None) -> list[dict[str, Any]]:
    queries = [json.loads(line) for line in QUERY_PATH.read_text(encoding="utf-8").splitlines()]
    return [query for query in queries if split is None or query["split"] == split]


def in_scope(document: Any, query: dict[str, Any]) -> bool:
    return document.applies_to(
        tenant_id=query["tenant_id"],
        region=query["region"],
        at=date.fromisoformat(query["at"]),
    )


def score_cases(cases: list[dict[str, Any]], queries: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {query["query_id"]: query for query in queries}
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    empty_results: list[bool] = []
    must_not_pass: list[bool] = []
    for case in cases:
        query = by_id[case["query_id"]]
        expected = set(query["expected_policy_ids"])
        actual = case["policy_ids"]
        forbidden = set(query.get("must_not_include", ()))
        must_not_pass.append(not forbidden.intersection(actual))
        if expected:
            recalls.append(len(expected.intersection(actual)) / len(expected))
            rank = next(
                (index + 1 for index, value in enumerate(actual) if value in expected),
                None,
            )
            reciprocal_ranks.append(1 / rank if rank else 0.0)
        else:
            empty_results.append(not actual)
    latencies = sorted(case["latency_ms"] for case in cases)
    p95_index = max(0, round(len(latencies) * 0.95) - 1)
    return {
        "query_count": len(cases),
        "recall_at_k": round(mean(recalls), 4) if recalls else None,
        "mrr": round(mean(reciprocal_ranks), 4) if reciprocal_ranks else None,
        "empty_result_rate": round(mean(empty_results), 4) if empty_results else None,
        "must_not_precision": round(mean(must_not_pass), 4) if must_not_pass else None,
        "p50_ms": round(latencies[len(latencies) // 2], 3) if latencies else None,
        "p95_ms": round(latencies[p95_index], 3) if latencies else None,
    }


def semantic_results(
    documents: tuple[Any, ...],
    vectors: tuple[tuple[float, ...], ...],
    query_vector: tuple[float, ...],
) -> tuple[RankedPolicy, ...]:
    if not documents:
        return ()
    return InMemorySemanticPolicyStore(documents, vectors).search(
        query_vector,
        limit=len(documents),
    )


async def run(args: argparse.Namespace) -> dict[str, Any]:
    documents = load_policy_documents(POLICY_PATH)
    queries = load_queries(args.split)
    required_inputs = len(documents) + len(queries)
    if not args.live_embedding:
        raise SystemExit("语义、Hybrid 和 rerank 实验必须显式传 --live-embedding")
    if required_inputs > args.max_inputs:
        raise SystemExit(
            f"本次需要 {required_inputs} 条 Embedding 输入，超过 --max-inputs={args.max_inputs}；"
            "如需 100/300 规模测试，请先确认并显式提高上限。"
        )
    embedding = OpenAICompatibleEmbedding.from_environment()
    inputs = [document.content for document in documents] + [query["query"] for query in queries]
    vectors = embedding.embed(inputs)
    document_vectors = vectors[: len(documents)]
    query_vectors = vectors[len(documents) :]
    exact = ExactPolicyStore(documents)
    cases_by_arm: dict[str, list[dict[str, Any]]] = {arm: [] for arm in args.arms}
    for query, query_vector in zip(queries, query_vectors, strict=True):
        scoped_indexes = [
            index for index, document in enumerate(documents) if in_scope(document, query)
        ]
        scoped = tuple(documents[index] for index in scoped_indexes)
        scoped_vectors = tuple(document_vectors[index] for index in scoped_indexes)
        bm25 = PolicyBM25(scoped)
        semantic = semantic_results(scoped, scoped_vectors, query_vector)
        for arm in args.arms:
            started = time.perf_counter()
            if arm == "exact":
                evidence = await exact.search(
                    query["query"],
                    tenant_id=query["tenant_id"],
                    region=query["region"],
                    at=date.fromisoformat(query["at"]),
                    limit=args.top_k,
                )
                results = tuple(
                    RankedPolicy(item.document, item.score, item.rank, "exact")
                    for item in evidence
                )
            elif arm == "bm25":
                results = bm25.search(query["query"], limit=args.top_k)
            elif arm == "semantic":
                results = semantic[: args.top_k]
            elif arm == "hybrid":
                candidates = fuse_policy_results(
                    (
                        ("semantic", semantic[: args.candidate_k]),
                        ("bm25", bm25.search(query["query"], limit=args.candidate_k)),
                    ),
                    limit=args.candidate_k,
                )
                results = candidates[: args.top_k]
            else:
                raise ValueError(f"未知检索 arm: {arm}")
            cases_by_arm[arm].append(
                {
                    "query_id": query["query_id"],
                    "policy_ids": [item.document.policy_id for item in results],
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }
            )
    config = vars(args).copy()
    config["output"] = str(args.output) if args.output else None
    return {
        "methodology": {
            "dataset": POLICY_PATH.name,
            "query_set": QUERY_PATH.name,
            "document_count": len(documents),
            "query_count": len(queries),
            "embedding_model": embedding.model,
            "embedding_dimension": embedding.dimension,
            "live_api": True,
            "note": "指标只适用于本次语料、查询划分和配置；holdout 不用于调参。",
        },
        "arms": {
            arm: {"config": config, "metrics": score_cases(cases, queries), "cases": cases}
            for arm, cases in cases_by_arm.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="ServiceFlow 009 Policy RAG retrieval experiment")
    parser.add_argument("--live-embedding", action="store_true")
    parser.add_argument("--split", choices=("train", "dev", "test", "holdout"))
    parser.add_argument("--max-inputs", type=int, default=64)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=10)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--arms",
        nargs="+",
        default=("exact", "bm25", "semantic", "hybrid"),
    )
    args = parser.parse_args()
    result = asyncio.run(run(args))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"result_written={args.output}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
