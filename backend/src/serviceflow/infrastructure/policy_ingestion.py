import json
import os
from pathlib import Path

from serviceflow.domain.policy_documents import PolicyDocument
from serviceflow.infrastructure.embedding_model import OpenAICompatibleEmbedding
from serviceflow.infrastructure.qdrant_policy_store import (
    ExactPolicyStore,
    PolicyRetriever,
    QdrantPolicyStore,
)
from serviceflow.infrastructure.rerank_model import QwenTextReranker

DEFAULT_POLICY_PATH = (
    Path(__file__).parents[4]
    / "experiments"
    / "policy_documents"
    / "serviceflow_policy_v2_expanded.jsonl"
)
def load_policy_documents(path: Path = DEFAULT_POLICY_PATH) -> tuple[PolicyDocument, ...]:
    documents = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"政策文件第 {line_number} 行不是合法 JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"政策文件第 {line_number} 行必须是 JSON 对象")
        documents.append(PolicyDocument.from_mapping(value))
    if not documents:
        raise ValueError("政策文件不能为空")
    return tuple(documents)


def build_default_policy_retriever(*, telemetry=None) -> PolicyRetriever:
    policy_path = os.getenv("SERVICEFLOW_POLICY_DOCUMENTS_PATH")
    documents = load_policy_documents(Path(policy_path) if policy_path else DEFAULT_POLICY_PATH)
    exact_store = ExactPolicyStore(documents)
    qdrant_url = os.getenv("SERVICEFLOW_QDRANT_URL")
    qdrant_store = None
    if qdrant_url:
        qdrant_store = QdrantPolicyStore.from_url(
            qdrant_url,
            embedding=OpenAICompatibleEmbedding.from_environment(),
            collection_name="serviceflow_policy_v2_complete_qwen3_7_text_embedding_hnsw_m16_ef128_v1",
            hnsw_full_scan_threshold=10,
            indexing_threshold=1,
        )
    reranker = None
    if os.getenv("SERVICEFLOW_RERANK_ENABLED", "false").casefold() == "true":
        reranker = QwenTextReranker.from_environment()
    candidate_limit = int(os.getenv("SERVICEFLOW_RERANK_CANDIDATE_K", "10"))
    if candidate_limit <= 0:
        raise ValueError("SERVICEFLOW_RERANK_CANDIDATE_K 必须是正整数")
    return PolicyRetriever(
        exact_store,
        qdrant_store,
        reranker=reranker,
        candidate_limit=candidate_limit,
        telemetry=telemetry,
    )
