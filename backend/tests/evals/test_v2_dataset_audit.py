from pathlib import Path

from serviceflow.evaluation.dataset_audit import (
    audit_v2_dataset,
    load_policy_score_scope,
    write_v2_audit,
)


def test_current_v2_dataset_is_audited_as_not_ready_for_quality_experiments() -> None:
    audit = audit_v2_dataset()

    assert audit.status == "blocked"
    assert audit.case_count == 132
    assert audit.split_counts == {
        "boundary_security": 24,
        "golden": 10,
        "holdout": 16,
        "reliability_concurrency": 12,
        "regression": 64,
        "smoke": 6,
    }
    assert audit.tool_assertion_cases == 0
    assert audit.state_transition_cases == 4
    assert audit.fpr_probe_cases == 9
    assert {
        "missing_dev_split",
        "tool_assertions_incomplete",
        "state_transition_assertions_incomplete",
    } <= set(audit.blockers)
    assert "policy_evidence_mapping_missing" not in audit.blockers
    assert "fpr_sample_size_small" in audit.warnings


def test_audit_uses_supplied_trace_directory(tmp_path: Path) -> None:
    audit = audit_v2_dataset(trace_dir=tmp_path)

    assert audit.trace_files == 0
    assert audit.dataset_version.startswith("v2-")


def test_write_v2_audit_creates_machine_readable_result(tmp_path: Path) -> None:
    output = tmp_path / "audit.json"

    write_v2_audit(audit_v2_dataset(), output)

    assert output.exists()
    assert '"status": "blocked"' in output.read_text(encoding="utf-8")


def test_policy_score_scope_explicitly_keeps_business_and_rag_namespaces_separate() -> None:
    scope = load_policy_score_scope()

    assert scope["relationship"] == "separate_namespaces"
    assert scope["business_policy"]["id_prefix"] == "POL-"
    assert scope["rag_evidence"]["id_prefixes"] == ["CN-", "SF-"]
