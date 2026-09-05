from collections import Counter
from pathlib import Path

from serviceflow.infrastructure.policy_ingestion import load_policy_documents


def test_complete_policy_corpus_has_four_registered_business_layers() -> None:
    path = (
        Path(__file__).parents[3]
        / "experiments"
        / "policy_documents"
        / "serviceflow_policy_v2_complete.jsonl"
    )
    documents = load_policy_documents(path)
    counts = Counter(document.source_type for document in documents)

    assert len(documents) == 103
    assert len({document.policy_id for document in documents}) == 103
    assert counts == {
        "regulation": 33,
        "local_guidance": 14,
        "project_internal": 20,
        "sop": 12,
        "faq": 12,
        "category_rule": 12,
    }
    assert all(document.source_hash for document in documents)
