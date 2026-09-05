import re
from collections.abc import Sequence
from datetime import date
from hashlib import sha256
from math import sqrt
from typing import Any, Protocol

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    HnswConfigDiff,
    MatchValue,
    MinShould,
    OptimizersConfigDiff,
    PointStruct,
    Range,
    SearchParams,
    VectorParams,
)

from serviceflow.domain.policy_documents import PolicyDocument, PolicyEvidence
from serviceflow.infrastructure.otel import Telemetry
from serviceflow.infrastructure.policy_retrieval import (
    PolicyBM25,
    PolicyReranker,
    RankedPolicy,
    fuse_policy_results,
    rerank_policy_results_with_model,
)


class Embedding(Protocol):
    dimension: int | None

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...


class HashEmbedding:
    dimension = 128

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(self._embed_one(text) for text in texts)

    def _embed_one(self, text: str) -> tuple[float, ...]:
        vector = [0.0] * self.dimension
        terms = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower())
        for term in terms:
            digest = sha256(term.encode()).digest()
            index = int.from_bytes(digest[:2], "big") % self.dimension
            vector[index] += 1.0
        norm = sqrt(sum(value * value for value in vector))
        return tuple(value / norm for value in vector) if norm else tuple(vector)


class QdrantPolicyStore:
    def __init__(
        self,
        client: AsyncQdrantClient,
        *,
        embedding: Embedding,
        collection_name: str = "serviceflow_policy_v2_qwen3_7_text_embedding",
        hnsw_m: int = 16,
        hnsw_ef_construction: int = 128,
        hnsw_ef_search: int = 64,
        hnsw_full_scan_threshold: int = 10000,
        indexing_threshold: int = 20000,
    ) -> None:
        self._client = client
        self._embedding = embedding
        self._collection_name = collection_name
        self._hnsw_m = hnsw_m
        self._hnsw_ef_construction = hnsw_ef_construction
        self._hnsw_ef_search = hnsw_ef_search
        self._hnsw_full_scan_threshold = hnsw_full_scan_threshold
        self._indexing_threshold = indexing_threshold

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        embedding: Embedding,
        collection_name: str = "serviceflow_policy_v2_qwen3_7_text_embedding",
        hnsw_m: int = 16,
        hnsw_ef_construction: int = 128,
        hnsw_ef_search: int = 64,
        hnsw_full_scan_threshold: int = 10000,
        indexing_threshold: int = 20000,
    ) -> "QdrantPolicyStore":
        return cls(
            AsyncQdrantClient(url=url),
            embedding=embedding,
            collection_name=collection_name,
            hnsw_m=hnsw_m,
            hnsw_ef_construction=hnsw_ef_construction,
            hnsw_ef_search=hnsw_ef_search,
            hnsw_full_scan_threshold=hnsw_full_scan_threshold,
            indexing_threshold=indexing_threshold,
        )

    async def ensure_collection(self) -> None:
        if self._embedding.dimension is None:
            raise ValueError("必须先生成 Embedding，才能创建 Qdrant collection")
        collections = await self._client.get_collections()
        names = {collection.name for collection in collections.collections}
        if self._collection_name not in names:
            await self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=VectorParams(
                    size=self._embedding.dimension,
                    distance=Distance.COSINE,
                ),
                hnsw_config=HnswConfigDiff(
                    m=self._hnsw_m,
                    ef_construct=self._hnsw_ef_construction,
                    full_scan_threshold=self._hnsw_full_scan_threshold,
                ),
                optimizers_config=OptimizersConfigDiff(
                    indexing_threshold=self._indexing_threshold,
                ),
            )
            return
        info = await self._client.get_collection(self._collection_name)
        vectors = info.config.params.vectors
        if getattr(vectors, "size", None) != self._embedding.dimension:
            raise ValueError("已有 Qdrant collection 的向量维度不匹配")

    async def collection_exists(self) -> bool:
        collections = await self._client.get_collections()
        return self._collection_name in {item.name for item in collections.collections}

    async def describe(self) -> dict[str, Any]:
        info = await self._client.get_collection(self._collection_name)
        vectors = info.config.params.vectors
        return {
            "collection": self._collection_name,
            "status": str(info.status),
            "points_count": info.points_count,
            "indexed_vectors_count": info.indexed_vectors_count,
            "vector_size": getattr(vectors, "size", None),
            "distance": str(getattr(vectors, "distance", None)),
            "hnsw_config": str(info.config.hnsw_config),
            "configured_hnsw": {
                "m": self._hnsw_m,
                "ef_construct": self._hnsw_ef_construction,
                "ef_search": self._hnsw_ef_search,
                "full_scan_threshold": self._hnsw_full_scan_threshold,
                "indexing_threshold": self._indexing_threshold,
            },
        }

    async def upsert(self, documents: Sequence[PolicyDocument]) -> None:
        vectors = self._embedding.embed([document.content for document in documents])
        if len(vectors) != len(documents):
            raise ValueError("Embedding 返回数量与政策数量不一致")
        dimensions = len(vectors[0]) if vectors else 0
        if not dimensions or any(len(vector) != dimensions for vector in vectors):
            raise ValueError("Embedding 返回向量维度不一致")
        if self._embedding.dimension is None:
            self._embedding.dimension = dimensions
        if self._embedding.dimension != dimensions:
            raise ValueError("Embedding 维度与适配器声明不一致")
        await self.ensure_collection()
        points = [
            PointStruct(
                id=_point_id(document),
                vector=list(vector),
                payload=_payload(document),
            )
            for document, vector in zip(documents, vectors, strict=True)
        ]
        await self._client.upsert(collection_name=self._collection_name, points=points, wait=True)

    async def search(
        self,
        query: str,
        *,
        tenant_id: str,
        region: str,
        at: Any,
        limit: int,
    ) -> tuple[PolicyEvidence, ...]:
        response = await self._client.query_points(
            collection_name=self._collection_name,
            query=list(self._embedding.embed([query])[0]),
            query_filter=_filter(tenant_id=tenant_id, region=region, at=at),
            limit=limit,
            with_payload=True,
            search_params=SearchParams(hnsw_ef=self._hnsw_ef_search),
        )
        evidence = []
        for rank, point in enumerate(response.points, 1):
            payload = dict(point.payload or {})
            evidence.append(
                PolicyEvidence(
                    document=PolicyDocument.from_mapping(payload),
                    score=float(point.score),
                    rank=rank,
                )
            )
        return tuple(evidence)


class ExactPolicyStore:
    def __init__(self, documents: Sequence[PolicyDocument]) -> None:
        self._documents = tuple(documents)

    @property
    def documents(self) -> tuple[PolicyDocument, ...]:
        return self._documents

    async def search(
        self,
        query: str,
        *,
        tenant_id: str,
        region: str,
        at: Any,
        limit: int,
    ) -> tuple[PolicyEvidence, ...]:
        query_terms = set(_terms(query))
        scored = []
        for document in self._documents:
            if not document.applies_to(tenant_id=tenant_id, region=region, at=at):
                continue
            document_terms = set(_terms(f"{document.title} {document.content}"))
            score = len(query_terms & document_terms)
            if score:
                scored.append((score, document))
        scored.sort(key=lambda item: (-item[0], item[1].policy_id))
        return tuple(
            PolicyEvidence(document=document, score=float(score), rank=rank)
            for rank, (score, document) in enumerate(scored[:limit], 1)
        )


class PolicyRetriever:
    def __init__(
        self,
        exact_store: ExactPolicyStore,
        qdrant_store: QdrantPolicyStore | None = None,
        reranker: PolicyReranker | None = None,
        candidate_limit: int = 10,
        telemetry: Telemetry | None = None,
    ) -> None:
        self._exact = exact_store
        self._qdrant = qdrant_store
        self._reranker = reranker
        self._candidate_limit = candidate_limit
        self._telemetry = telemetry

    async def prepare(self) -> str:
        if self._qdrant is None:
            return "exact"
        try:
            if await self._qdrant.collection_exists():
                return "qdrant_hnsw"
            await self._qdrant.upsert(self._exact.documents)
        except Exception:
            return "exact_fallback"
        return "qdrant_hnsw"

    async def retrieve(
        self,
        query: str,
        *,
        tenant_id: str,
        region: str,
        at: Any,
        limit: int = 5,
    ) -> tuple[tuple[PolicyEvidence, ...], str, str | None]:
        if self._qdrant is not None:
            try:
                scoped_documents = tuple(
                    document
                    for document in self._exact.documents
                    if document.applies_to(tenant_id=tenant_id, region=region, at=at)
                )
                coarse_limit = max(limit, self._candidate_limit)
                lexical_results = PolicyBM25(scoped_documents).search(query, limit=coarse_limit)
                semantic_evidence = await self._qdrant.search(
                    query,
                    tenant_id=tenant_id,
                    region=region,
                    at=at,
                    limit=coarse_limit,
                )
                semantic_results = tuple(
                    RankedPolicy(item.document, item.score, item.rank, "semantic")
                    for item in semantic_evidence
                )
                fused = fuse_policy_results(
                    (("semantic", semantic_results), ("bm25", lexical_results)),
                    limit=coarse_limit,
                )
                recalled_ids = [item.document.policy_id for item in fused]
                if self._reranker is not None:
                    try:
                        fused = rerank_policy_results_with_model(
                            query,
                            fused,
                            reranker=self._reranker,
                            limit=limit,
                        )
                        backend = "qdrant_hybrid_rerank"
                    except Exception as exc:
                        self._trace(recalled_ids, recalled_ids[:limit], empty=not fused)
                        return (
                            tuple(
                                PolicyEvidence(item.document, item.score, item.rank)
                                for item in fused[:limit]
                            ),
                            "qdrant_hybrid_rerank_fallback",
                            type(exc).__name__,
                        )
                else:
                    backend = "qdrant_hybrid"
                self._trace(
                    recalled_ids,
                    [item.document.policy_id for item in fused],
                    empty=not fused,
                )
                return (
                    tuple(
                        PolicyEvidence(item.document, item.score, item.rank)
                        for item in fused
                    ),
                    backend,
                    None,
                )
            except Exception as exc:
                fallback = await self._exact.search(
                    query,
                    tenant_id=tenant_id,
                    region=region,
                    at=at,
                    limit=limit,
                )
                fallback_ids = [item.document.policy_id for item in fallback]
                self._trace(fallback_ids, fallback_ids, empty=not fallback)
                return fallback, "exact_fallback", type(exc).__name__
        exact = await self._exact.search(
            query,
            tenant_id=tenant_id,
            region=region,
            at=at,
            limit=limit,
        )
        exact_ids = [item.document.policy_id for item in exact]
        self._trace(exact_ids, exact_ids, empty=not exact)
        return exact, "exact", None

    def _trace(self, recalled: list[str], reranked: list[str], *, empty: bool) -> None:
        if self._telemetry is None:
            return
        with self._telemetry.span(
            "retrieval.policy",
            attributes={
                "serviceflow.retrieval.recalled_ids": recalled,
                "serviceflow.retrieval.reranked_ids": reranked,
                "serviceflow.retrieval.empty": empty,
            },
        ):
            pass

    def trace_prompt_ids(self, policy_ids: list[str]) -> None:
        if self._telemetry is None:
            return
        with self._telemetry.span(
            "context.policy_evidence",
            attributes={"serviceflow.retrieval.prompt_ids": policy_ids},
        ):
            pass


def _terms(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower())


def _point_id(document: PolicyDocument) -> str:
    return sha256(f"{document.policy_id}:{document.version}".encode()).hexdigest()[:32]


def _payload(document: PolicyDocument) -> dict[str, Any]:
    return {
        "policy_id": document.policy_id,
        "version": document.version,
        "title": document.title,
        "content": document.content,
        "tenant_id": document.tenant_id or "__global__",
        "region": document.region or "__global__",
        "effective_from": document.effective_from.isoformat(),
        "effective_to": (document.effective_to or date.max).isoformat(),
        "effective_from_ord": document.effective_from.toordinal(),
        "effective_to_ord": (document.effective_to or date.max).toordinal(),
        "source_type": document.source_type,
        "source_title": document.source_title,
        "source_url": document.source_url,
        "source_locator": document.source_locator,
        "source_hash": document.source_hash,
    }


def _filter(*, tenant_id: str, region: str, at: Any) -> Filter:
    at_value = at.toordinal()
    scope_conditions = [
        FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
        FieldCondition(key="tenant_id", match=MatchValue(value="__global__")),
        FieldCondition(key="region", match=MatchValue(value=region)),
        FieldCondition(key="region", match=MatchValue(value="__global__")),
    ]
    return Filter(
        must=[
            FieldCondition(key="effective_from_ord", range=Range(lte=at_value)),
            FieldCondition(key="effective_to_ord", range=Range(gte=at_value)),
        ],
        min_should=MinShould(conditions=scope_conditions, min_count=2),
    )
