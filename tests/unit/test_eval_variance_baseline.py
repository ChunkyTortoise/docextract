"""Unit tests for variance-calibrated eval gate tolerance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_gate import (
    RELATIVE_DROP_TOLERANCE,
    check_thresholds,
    load_relative_tolerance,
)
from scripts.eval_variance_baseline import compute_tolerance


def test_compute_tolerance_uses_two_stdev_or_floor() -> None:
    # Identical runs -> stdev 0 -> floor 0.005
    runs = [{"faithfulness": 0.90, "extraction_f1": 0.95} for _ in range(5)]
    payload = compute_tolerance(runs, floor=0.005, stdev_mult=2.0)
    assert payload["relative_drop_tolerance"] == pytest.approx(0.005)
    assert payload["per_metric"]["faithfulness"]["stdev"] == pytest.approx(0.0)


def test_compute_tolerance_scales_with_stdev() -> None:
    runs = [
        {"faithfulness": 0.90},
        {"faithfulness": 0.92},
        {"faithfulness": 0.88},
        {"faithfulness": 0.91},
        {"faithfulness": 0.89},
        {"faithfulness": 0.905},
        {"faithfulness": 0.895},
    ]
    payload = compute_tolerance(runs, floor=0.005, stdev_mult=2.0)
    metric_tol = payload["per_metric"]["faithfulness"]["tolerance"]
    assert payload["relative_drop_tolerance"] == pytest.approx(metric_tol)
    assert payload["relative_drop_tolerance"] > 0.005
    assert payload["per_metric"]["faithfulness"]["stdev"] > 0


def test_compute_tolerance_requires_two_samples() -> None:
    with pytest.raises(ValueError):
        compute_tolerance([{"faithfulness": 0.9}])


def test_check_thresholds_honors_custom_tolerance() -> None:
    combined = {"faithfulness": 0.90}
    baseline = {"faithfulness": 0.95}  # ~5.3% drop
    # With tight tolerance, fails
    fails = check_thresholds(combined, baseline, relative_drop_tolerance=0.03)
    assert any(f["metric"] == "faithfulness" for f in fails)
    # With loose calibrated tolerance, passes relative check (may still fail floor)
    fails_loose = check_thresholds(combined, baseline, relative_drop_tolerance=0.10)
    assert not any("dropped" in f["reason"] for f in fails_loose)


def test_load_relative_tolerance_reads_artifact(tmp_path: Path) -> None:
    path = tmp_path / "variance_baseline.json"
    path.write_text(json.dumps({"relative_drop_tolerance": 0.017}))
    assert load_relative_tolerance(path) == pytest.approx(0.017)


def test_load_relative_tolerance_falls_back(tmp_path: Path) -> None:
    assert load_relative_tolerance(tmp_path / "missing.json") == RELATIVE_DROP_TOLERANCE
