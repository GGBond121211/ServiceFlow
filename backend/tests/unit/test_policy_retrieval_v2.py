from serviceflow.domain.policy_documents import PolicyDocument
from serviceflow.infrastructure.policy_retrieval import (
    InMemorySemanticPolicyStore,
    PolicyBM25,
    RankedPolicy,
    cosine_similarity,
    fuse_policy_results,
    rerank_policy_results_with_model,
)
from serviceflow.infrastructure.rerank_model import RerankResult


def policy(policy_id: str, title: str, content: str) -> PolicyDocument:
    return PolicyDocument.from_mapping(
        {
            "policy_id": policy_id,
            "version": "v2",
            "title": title,
            "content": content,
            "tenant_id": None,
            "region": "CN",
            "effective_from": "2026-01-01",
            "source_type": "project_internal",
            "source_title": "测试法规",
            "source_url": "https://example.test/policy",
            "source_locator": "第一条",
        }
    )


def test_bm25_indexes_policy_id_and_source_fields() -> None:
    documents = (
        policy("CN-7DAY-002", "七日期间起算", "签收次日开始计算"),
        policy("CN-QUALITY-003", "质量售后运费", "质量换货的必要运输费用"),
    )

    result = PolicyBM25(documents).search("CN-7DAY-002")

    assert result[0].document.policy_id == "CN-7DAY-002"


def test_semantic_store_orders_by_cosine_and_hybrid_preserves_evidence() -> None:
    first = policy("P-1", "质量维修", "商品质量问题维修")
    second = policy("P-2", "普通退货", "七日无理由退货")
    semantic = InMemorySemanticPolicyStore((first, second), ((1.0, 0.0), (0.0, 1.0)))
    semantic_results = semantic.search((0.9, 0.1), limit=2)
    lexical_results = (
        RankedPolicy(second, 4.0, 1, "bm25"),
        RankedPolicy(first, 1.0, 2, "bm25"),
    )

    fused = fuse_policy_results((("semantic", semantic_results), ("bm25", lexical_results)))

    assert semantic_results[0].document.policy_id == "P-1"
    assert fused[0].retrieval_reason == "hybrid_match"
    assert {item.document.policy_id for item in fused} == {"P-1", "P-2"}
    assert cosine_similarity((1.0, 0.0), (0.0, 1.0)) == 0.0


def test_model_rerank_maps_provider_indexes_back_to_policy_documents() -> None:
    first = policy("P-1", "质量维修", "商品质量问题维修")
    second = policy("P-2", "普通退货", "七日无理由退货")
    candidates = (
        RankedPolicy(first, 0.02, 1, "hybrid_match"),
        RankedPolicy(second, 0.03, 2, "hybrid_match"),
    )

    class FakeReranker:
        def rerank(self, query: str, documents: tuple[str, ...], *, top_n: int):
            assert query == "哪条政策回答问题"
            assert len(documents) == 2
            assert top_n == 2
            return (RerankResult(1, 0.91), RerankResult(0, 0.12))

    result = rerank_policy_results_with_model(
        "哪条政策回答问题",
        candidates,
        reranker=FakeReranker(),
        limit=2,
    )

    assert [item.document.policy_id for item in result] == ["P-2", "P-1"]
    assert [item.retrieval_reason for item in result] == ["cross_encoder", "cross_encoder"]
