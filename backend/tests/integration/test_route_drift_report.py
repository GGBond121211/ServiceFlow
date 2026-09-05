import pytest

from serviceflow.infrastructure.model_profiles import route_drift_report


def test_route_drift_requires_recheck_after_distribution_shift() -> None:
    report = route_drift_report(
        baseline={"deepseek-v4-flash": 0.9, "backup-low-cost": 0.1},
        current={"deepseek-v4-flash": 0.6, "backup-low-cost": 0.4},
        quality_pass_rate=0.92,
        minimum_quality_pass_rate=0.95,
        shift_threshold=0.15,
    )

    assert report.drifted is True
    assert report.requires_model_ab is True
    assert report.max_distribution_shift == pytest.approx(0.3)
