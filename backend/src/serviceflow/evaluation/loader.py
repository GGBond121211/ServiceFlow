from collections.abc import Sequence
from pathlib import Path

from serviceflow.evaluation.models import EvalCase

DEFAULT_EVAL_PATH = Path(__file__).parents[4] / "tests" / "eval_cases" / "serviceflow_v1.jsonl"


def load_eval_cases(path: Path | Sequence[Path] = DEFAULT_EVAL_PATH) -> list[EvalCase]:
    if isinstance(path, Path):
        paths = (path,)
    else:
        paths = tuple(path)

    cases = []
    for case_path in paths:
        lines = case_path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            if line.strip():
                cases.append(EvalCase.model_validate_json(line))

    ids = []
    for case in cases:
        ids.append(case.id)
    if len(ids) != len(set(ids)):
        raise ValueError("所有评测分区中的案例 ID 必须唯一")
    return cases
