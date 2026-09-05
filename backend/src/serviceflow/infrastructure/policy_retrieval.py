from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from serviceflow.domain.policy_documents import PolicyDocument
from serviceflow.infrastructure.rerank_model import RerankResult

_RRF_K = 60


def policy_terms(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.casefold()))


def searchable_policy_text(document: PolicyDocument) -> str:
    return " ".join(
        (
            document.policy_id,
            document.version,
            document.title,
            document.content,
            document.source_title,
            document.source_locator,
        )
    )


def _idf(document_count: int, document_frequency: int) -> float:
    return math.log1p((document_count - document_frequency + 0.5) / (document_frequency + 0.5))


@dataclass(frozen=True, slots=True)
class RankedPolicy:
    document: PolicyDocument
    score: float
    rank: int
    retrieval_reason: str


class PolicyReranker(Protocol):
    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int,
    ) -> tuple[RerankResult, ...]: ...


class PolicyBM25:
    def __init__(self, documents: Sequence[PolicyDocument], *, k1: float = 1.2, b: float = 0.75):
        self._documents = tuple(documents)
        self._k1 = k1
        self._b = b

    def search(self, query: str, *, limit: int = 5) -> tuple[RankedPolicy, ...]:
        if limit <= 0:
            raise ValueError("limit 必须是正整数")
        query_tokens = policy_terms(query)
        if not query_tokens or not self._documents:
            return ()
        tokenized = [policy_terms(searchable_policy_text(document)) for document in self._documents]
        lengths = [len(tokens) for tokens in tokenized]
        average_length = sum(lengths) / len(lengths)
        if average_length == 0:
            return ()
        frequencies = Counter(token for tokens in tokenized for token in set(tokens))
        scored: list[tuple[float, PolicyDocument]] = []
        for document, tokens, length in zip(self._documents, tokenized, lengths, strict=True):
            counts = Counter(tokens)
            normalization = 1.0 - self._b + self._b * length / average_length
            score = 0.0
            for token in set(query_tokens):
                frequency = counts.get(token, 0)
                if frequency:
                    score += _idf(len(self._documents), frequencies[token]) * (
                        frequency * (self._k1 + 1.0) / (frequency + self._k1 * normalization)
                    )
            if score > 0.0:
                scored.append((score, document))
        scored.sort(key=lambda item: (-item[0], item[1].policy_id))
        return tuple(
            RankedPolicy(document, score, rank, "bm25")
            for rank, (score, document) in enumerate(scored[:limit], 1)
        )


def cosine_similarity(first: Sequence[float], second: Sequence[float]) -> float:
    if len(first) != len(second):
        raise ValueError("查询向量与文档向量的维度不匹配")
    first_norm = math.sqrt(sum(value * value for value in first))
    second_norm = math.sqrt(sum(value * value for value in second))
    if first_norm == 0 or second_norm == 0:
        return 0.0
    return sum(left * right for left, right in zip(first, second, strict=True)) / (
        first_norm * second_norm
    )


class InMemorySemanticPolicyStore:
    def __init__(self, documents: Sequence[PolicyDocument], vectors: Sequence[Sequence[float]]):
        if len(documents) != len(vectors) or not documents:
            raise ValueError("文档和向量必须一一对应且不能为空")
        self._documents = tuple(documents)
        self._vectors = tuple(tuple(vector) for vector in vectors)

    def search(
        self,
        query_vector: Sequence[float],
        *,
        limit: int = 5,
        min_score: float = 0.0,
    ) -> tuple[RankedPolicy, ...]:
        if limit <= 0:
            raise ValueError("limit 必须是正整数")
        scored = [
            (cosine_similarity(query_vector, vector), document)
            for document, vector in zip(self._documents, self._vectors, strict=True)
        ]
        scored = [(score, document) for score, document in scored if score >= min_score]
        scored.sort(key=lambda item: (-item[0], item[1].policy_id))
        return tuple(
            RankedPolicy(document, score, rank, "semantic")
            for rank, (score, document) in enumerate(scored[:limit], 1)
        )


def fuse_policy_results(
    sources: Sequence[tuple[str, Sequence[RankedPolicy]]], *, limit: int = 5
) -> tuple[RankedPolicy, ...]:
    if limit <= 0:
        raise ValueError("limit 必须是正整数")
    scores: defaultdict[str, float] = defaultdict(float)
    documents: dict[str, PolicyDocument] = {}
    reasons: defaultdict[str, set[str]] = defaultdict(set)
    for source_name, results in sources:
        weight = 1.0 if source_name == "bm25" else 0.8
        for result in results:
            policy_id = result.document.policy_id
            scores[policy_id] += weight / (_RRF_K + result.rank)
            documents[policy_id] = result.document
            reasons[policy_id].add(result.retrieval_reason)
    ordered = sorted(scores, key=lambda policy_id: (-scores[policy_id], policy_id))[:limit]
    return tuple(
        RankedPolicy(
            documents[policy_id],
            scores[policy_id],
            rank,
            "hybrid_match" if len(reasons[policy_id]) > 1 else next(iter(reasons[policy_id])),
        )
        for rank, policy_id in enumerate(ordered, 1)
    )


def rerank_policy_results_with_model(
    query: str,
    candidates: Sequence[RankedPolicy],
    *,
    reranker: PolicyReranker,
    limit: int,
) -> tuple[RankedPolicy, ...]:
    if limit <= 0:
        raise ValueError("limit 必须是正整数")
    if not candidates:
        return ()
    results = reranker.rerank(
        query,
        [searchable_policy_text(item.document) for item in candidates],
        top_n=min(limit, len(candidates)),
    )
    reranked = []
    for rank, result in enumerate(results, 1):
        candidate = candidates[result.index]
        reranked.append(
            RankedPolicy(
                candidate.document,
                result.relevance_score,
                rank,
                "cross_encoder",
            )
        )
    return tuple(reranked)
