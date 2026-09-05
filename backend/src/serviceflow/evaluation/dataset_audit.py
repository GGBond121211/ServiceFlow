"""V2 评测集合的可执行就绪性审计。"""

from __future__ import annotations

import json
from collections import Counter
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from serviceflow.evaluation.case_v2 import EvalCaseV2, V2Category, V2Split

ROOT = Path(__file__).parents[4]
DEFAULT_V2_PATH = ROOT / "tests" / "eval_cases" / "serviceflow_v2.jsonl"
DEFAULT_TRACE_DIR = ROOT / "experiments" / "results" / "simulator_traces"
DEFAULT_POLICY_SCOPE_PATH = ROOT / "experiments" / "configs" / "policy_score_scope.json"


class V2DatasetAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_path: str
    dataset_version: str
    dataset_sha256: str
    status: str
    case_count: int
    split_counts: dict[str, int]
    category_counts: dict[str, int]
    tool_assertion_cases: int
    state_transition_cases: int
    fpr_probe_cases: int
    multi_turn_cases: int
    trace_files: int
    holdout_case_ids: list[str]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def audit_v2_dataset(
    path: Path = DEFAULT_V2_PATH,
    *,
    trace_dir: Path = DEFAULT_TRACE_DIR,
    policy_scope_path: Path = DEFAULT_POLICY_SCOPE_PATH,
) -> V2DatasetAudit:
    raw = path.read_bytes()
    cases = [
        EvalCaseV2.model_validate_json(line)
        for line in raw.decode("utf-8").splitlines()
        if line
    ]
    split_counts = Counter(case.split.value for case in cases)
    category_counts = Counter(case.category.value for case in cases)
    tool_assertion_cases = sum(bool(case.expected.expected_tool_calls) for case in cases)
    state_transition_cases = sum(bool(case.expected.state_transitions) for case in cases)
    fpr_probe_cases = category_counts[V2Category.FALSE_POSITIVE_PROBE.value]
    multi_turn_cases = category_counts[V2Category.MULTI_TURN_RECOVERY.value]
    trace_paths = tuple(trace_dir.glob("*.jsonl")) if trace_dir.exists() else ()
    trace_files = len(trace_paths)

    holdout = [case for case in cases if case.split is V2Split.HOLDOUT]
    tuning = [case for case in cases if case.split is not V2Split.HOLDOUT]
    tuning_orders = {case.initial_state.order_id for case in tuning if case.initial_state.order_id}
    tuning_reasons = {case.user_scenario.reason_for_call for case in tuning}
    blockers: list[str] = []
    if "dev" not in split_counts:
        blockers.append("missing_dev_split")
    if tool_assertion_cases < len(cases):
        blockers.append("tool_assertions_incomplete")
    if state_transition_cases < len(cases):
        blockers.append("state_transition_assertions_incomplete")
    trace_case_ids = {path.stem for path in trace_paths}
    required_trace_ids = {
        case.id for case in cases if case.category is V2Category.MULTI_TURN_RECOVERY
    }
    if required_trace_ids - trace_case_ids:
        blockers.append("simulator_traces_missing")
    if any(case.initial_state.order_id in tuning_orders for case in holdout):
        blockers.append("holdout_order_leakage")
    if any(case.user_scenario.reason_for_call in tuning_reasons for case in holdout):
        blockers.append("holdout_scenario_leakage")
    policy_scope = load_policy_score_scope(policy_scope_path)
    if policy_scope["relationship"] != "separate_namespaces":
        blockers.append("policy_evidence_mapping_missing")

    warnings: list[str] = []
    if fpr_probe_cases < 50:
        warnings.append("fpr_sample_size_small")
    if not cases:
        warnings.append("empty_dataset")
    digest = sha256(raw).hexdigest().upper()
    return V2DatasetAudit(
        dataset_path=str(path),
        dataset_version=f"v2-{digest[:12].lower()}",
        dataset_sha256=digest,
        status="ready" if not blockers else "blocked",
        case_count=len(cases),
        split_counts=dict(sorted(split_counts.items())),
        category_counts=dict(sorted(category_counts.items())),
        tool_assertion_cases=tool_assertion_cases,
        state_transition_cases=state_transition_cases,
        fpr_probe_cases=fpr_probe_cases,
        multi_turn_cases=multi_turn_cases,
        trace_files=trace_files,
        holdout_case_ids=[case.id for case in holdout],
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(warnings),
    )


def write_v2_audit(audit: V2DatasetAudit, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(audit.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_policy_score_scope(path: Path = DEFAULT_POLICY_SCOPE_PATH) -> dict[str, object]:
    if not path.is_file():
        raise ValueError(f"policy score scope not found: {path}")
    scope = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(scope, dict):
        raise ValueError("policy score scope must be an object")
    if scope.get("relationship") not in {"separate_namespaces", "explicit_mapping"}:
        raise ValueError("policy score scope has an unsupported relationship")
    for key in ("business_policy", "rag_evidence"):
        if not isinstance(scope.get(key), dict):
            raise ValueError(f"policy score scope missing {key}")
    return scope
