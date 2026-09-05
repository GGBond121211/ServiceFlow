from __future__ import annotations

import json
from pathlib import Path

from serviceflow.infrastructure.model_profiles import route_drift_report


def main() -> None:
    report = route_drift_report(
        baseline={"deepseek-v4-flash": 1.0, "gpt-5.6-luna": 0.0},
        current={"deepseek-v4-flash": 1.0, "gpt-5.6-luna": 0.0},
        quality_pass_rate=1.0,
        minimum_quality_pass_rate=0.95,
        shift_threshold=0.15,
    )
    payload = {
        "run_date": "2026-09-05",
        "route_version": "step8-v1",
        "scope": "four observed real gateway audit rows; routing only",
        "baseline": {"deepseek-v4-flash": 1.0, "gpt-5.6-luna": 0.0},
        "current": {"deepseek-v4-flash": 1.0, "gpt-5.6-luna": 0.0},
        "drifted": report.drifted,
        "max_distribution_shift": report.max_distribution_shift,
        "quality_gate_evaluated": False,
        "observed_task_quality_pass_rate": None,
        "requires_model_ab_from_distribution_only": report.drifted,
        "boundary": (
            "The four requests are smoke observations, not a Step 9 quality baseline. "
            "A synthetic drift contract is covered by test_route_drift_report.py."
        ),
    }
    root = Path(__file__).resolve().parents[1]
    output = root / "experiments/results/step8-route-drift-smoke-2026-09-05.json"
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
