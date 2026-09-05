"""实验入口：加载案例集、校验契约、按 ExperimentSpec 组织实验。

Step 1 阶段只实现**加载与校验**（计划验收条件："三个案例集能由同一 runner 加载，
案例契约错误会在 CI 中失败"）。实际执行 V2 案例需要 Step 5-7 的能力，届时再接。

用法：
    uv run python experiments/runner.py list
    uv run python experiments/runner.py validate
    uv run python experiments/runner.py spec-template > experiments/results/my-exp/spec.yaml
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _case_models() -> tuple[Any, Any]:
    """延迟导入：本脚本可在 backend 之外运行，需先把 src 加进 sys.path。"""
    src = str(ROOT / "backend" / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from serviceflow.evaluation.case_v2 import EvalCaseV2
    from serviceflow.evaluation.models import EvalCase

    return EvalCase, EvalCaseV2


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


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    {"list": cmd_list, "validate": cmd_validate, "spec-template": cmd_spec_template}.get(
        cmd, cmd_list
    )()


if __name__ == "__main__":
    main()
