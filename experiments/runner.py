"""实验入口：加载案例集、校验契约、按 ExperimentSpec 组织实验。

Step 1 阶段只实现**加载与校验**（计划验收条件："三个案例集能由同一 runner 加载，
案例契约错误会在 CI 中失败"）。Step 9 增加 V2 就绪性审计和结果评分入口；
它只消费真实执行证据，不为缺失证据补造通过结果。

用法：
    uv run python experiments/runner.py list
    uv run python experiments/runner.py validate
    uv run python experiments/runner.py audit-v2 [audit-result.json]
    uv run python experiments/runner.py score-v2 <raw-results.jsonl> [scored.jsonl]
    uv run python experiments/runner.py spec-template > experiments/results/my-exp/spec.yaml
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _case_models() -> tuple[Any, Any]:
    """延迟导入：本脚本可在 backend 之外运行，需先把 src 加进 sys.path。"""
    _add_source_path()
    from serviceflow.evaluation.case_v2 import EvalCaseV2
    from serviceflow.evaluation.models import EvalCase

    return EvalCase, EvalCaseV2


def _add_source_path() -> None:
    src = str(ROOT / "backend" / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


V1_CORE = ROOT / "tests" / "eval_cases" / "serviceflow_v1.jsonl"
V1_COMPLEX = ROOT / "tests" / "eval_cases" / "serviceflow_v1_complex_60.jsonl"
V2 = ROOT / "tests" / "eval_cases" / "serviceflow_v2.jsonl"


@dataclass
class ExperimentSpec:
    """每次实验的契约。**每次只允许改一个变量。**"""

    experiment_id: str
    hypothesis: str
    baseline: str
    candidate: str
    dataset_version: str
    fixed_variables: dict[str, Any] = field(default_factory=dict)
    changed_variable: dict[str, Any] = field(default_factory=dict)
    trials: int = 1
    metrics: tuple[str, ...] = ()
    latency_budget_ms: int | None = None
    cost_budget: float | None = None
    hard_gates: tuple[str, ...] = ()
    rollback: str = ""
    owner: str = ""
    timestamp: str = ""
    result_path: str = ""
    decision: str = ""

    def validate(self) -> None:
        if len(self.changed_variable) != 1:
            raise ValueError(
                f"{self.experiment_id}: 每次实验只能改一个变量，"
                f"当前 {len(self.changed_variable)} 个：{list(self.changed_variable)}"
            )
        if not self.metrics:
            raise ValueError(f"{self.experiment_id}: 必须声明 metrics")
        if not self.rollback:
            raise ValueError(f"{self.experiment_id}: 必须写明回滚方式")


def _read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def load_all() -> dict[str, list[Any]]:
    """同一入口加载三份案例集。任何契约错误都会在这里抛出。"""
    eval_case, eval_case_v2 = _case_models()
    core = [eval_case.model_validate(x) for x in _read_jsonl(V1_CORE)]
    complex_ = [eval_case.model_validate(x) for x in _read_jsonl(V1_COMPLEX)]
    v2 = [eval_case_v2.model_validate(x) for x in _read_jsonl(V2)]
    return {"v1_core": core, "v1_complex": complex_, "v2": v2}


def cmd_list() -> None:
    sets = load_all()
    print(f"v1_core     {len(sets['v1_core']):3d} 条  （冻结基线）")
    print(f"v1_complex  {len(sets['v1_complex']):3d} 条  （冻结基线）")
    print(f"v2          {len(sets['v2']):3d} 条")
    print("\nV2 划分：")
    for split, n in sorted(Counter(c.split.value for c in sets["v2"]).items()):
        mark = "  ← 全程锁定" if split == "holdout" else ""
        print(f"  {split:26s} {n:3d}{mark}")
    print("\nV2 注入变体：")
    for variant, n in sorted(
        Counter(c.injection_variant.value for c in sets["v2"] if c.injection_variant).items()
    ):
        print(f"  {variant:26s} {n:3d}")


def cmd_validate() -> None:
    sets = load_all()
    total = sum(len(v) for v in sets.values())
    v2 = sets["v2"]
    holdout_orders = {c.initial_state.order_id for c in v2 if c.split.value == "holdout"}
    tune_orders = {c.initial_state.order_id for c in v2 if c.split.value != "holdout"}
    leaked = {o for o in holdout_orders & tune_orders if o}
    if leaked:
        raise SystemExit(f"holdout 与调参集共用订单号：{sorted(leaked)}")
    print(f"契约校验通过：共 {total} 条（v1 100 + v2 {len(v2)}），holdout 无泄漏")


def cmd_spec_template() -> None:
    print(
        """experiment_id: exp-0001-<一句话>
hypothesis: <改变量 X 会让指标 Y 提升，代价是 Z>
baseline: v1-100-20260811
candidate: <候选配置标识>
dataset_version: v2-20260903
fixed_variables: {}      # 本次保持不变的全部配置
changed_variable: {}     # 只能有一个键
trials: 3
metrics: []
latency_budget_ms: null
cost_budget: null
hard_gates: []           # 必须包含误拦截率上限，见计划补充 A
rollback: <怎么退回 baseline>
owner: ""
timestamp: ""
result_path: experiments/results/exp-0001/
decision: ""             # 结论回写 DECISIONS.md 第几行"""
    )


def cmd_audit_v2() -> None:
    _add_source_path()
    from serviceflow.evaluation.dataset_audit import audit_v2_dataset, write_v2_audit

    audit = audit_v2_dataset()
    if len(sys.argv) >= 3:
        write_v2_audit(audit, pathlib.Path(sys.argv[2]))
    print(json.dumps(audit.model_dump(mode="json"), ensure_ascii=False, indent=2))
    if audit.status != "ready":
        raise SystemExit(2)


def cmd_score_v2() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(
            "用法：uv run python experiments/runner.py score-v2 "
            "<raw-results.jsonl> [scored.jsonl]"
        )
    _add_source_path()
    from serviceflow.evaluation.dataset_audit import audit_v2_dataset
    from serviceflow.evaluation.v2_runner import (
        V2Execution,
        run_v2_evaluation,
        write_v2_results,
    )

    cases = {case.id: case for case in load_all()["v2"]}
    input_path = pathlib.Path(sys.argv[2])
    executions: dict[str, Any] = {}
    selected_cases = []
    seen: set[str] = set()
    for line in input_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        case_id = str(payload["case_id"])
        if case_id in seen:
            raise SystemExit(f"重复执行结果：{case_id}")
        if case_id not in cases:
            raise SystemExit(f"结果中的未知案例：{case_id}")
        execution_payload = payload.get("execution", payload)
        executions[case_id] = V2Execution.model_validate(execution_payload)
        selected_cases.append(cases[case_id])
        seen.add(case_id)
    if not selected_cases:
        raise SystemExit("输入结果为空")

    async def replay(case: Any) -> V2Execution:
        return executions[case.id]

    run = asyncio.run(
        run_v2_evaluation(
            cases=selected_cases,
            executor=replay,
            dataset_version=audit_v2_dataset().dataset_version,
            experiment_id="score-v2",
            commit="unknown",
        )
    )
    if len(sys.argv) >= 4:
        write_v2_results(run.case_results, pathlib.Path(sys.argv[3]))
    print(json.dumps(run.summary.model_dump(mode="json"), ensure_ascii=False, indent=2))


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    commands = {
        "list": cmd_list,
        "validate": cmd_validate,
        "audit-v2": cmd_audit_v2,
        "score-v2": cmd_score_v2,
        "spec-template": cmd_spec_template,
    }
    commands.get(cmd, cmd_list)()


if __name__ == "__main__":
    main()
