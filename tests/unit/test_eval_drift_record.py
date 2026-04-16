"""Unit tests for scripts/eval_drift_record.py — pure-python logic, no API calls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_drift_record import detect_drift, load_history, z_score


# ---------------------------------------------------------------------------
# z_score
# ---------------------------------------------------------------------------


def test_z_score_correct_value() -> None:
    history = [0.90, 0.91, 0.89, 0.92, 0.88, 0.90, 0.91]
    z = z_score(0.85, history)  # below mean ~0.9014, stdev ~0.013
    assert z is not None
    assert z < -2.0  # clearly below mean


def test_z_score_positive_for_value_above_mean() -> None:
    history = [0.90, 0.91, 0.89, 0.92, 0.88, 0.90, 0.91]
    z = z_score(0.99, history)
    assert z is not None
    assert z > 2.0


def test_z_score_returns_none_with_fewer_than_3_history_points() -> None:
    assert z_score(0.85, [0.90, 0.91]) is None
    assert z_score(0.85, [0.90]) is None
    assert z_score(0.85, []) is None


def test_z_score_returns_none_when_stdev_near_zero() -> None:
    # All identical history values -> stdev ~ 0
    history = [0.90, 0.90, 0.90, 0.90, 0.90]
    assert z_score(0.85, history) is None


# ---------------------------------------------------------------------------
# detect_drift
# ---------------------------------------------------------------------------


def test_detect_drift_flags_metrics_above_z_threshold() -> None:
    # History with realistic variance so stdev > 0
    faithfulness_vals = [0.900, 0.912, 0.888, 0.905, 0.895, 0.910, 0.902]
    history = [{"faithfulness": v} for v in faithfulness_vals]
    # Current score is very far below the mean (~0.902), stdev ~0.008 -> z ~ -38
    current = {"faithfulness": 0.60}
    flagged = detect_drift(current, history)
    assert "faithfulness" in flagged
    assert flagged["faithfulness"] < -2.0


def test_detect_drift_empty_when_within_threshold() -> None:
    history = [{"faithfulness": 0.90} for _ in range(7)]
    current = {"faithfulness": 0.91}  # tiny positive change, z < 2
    flagged = detect_drift(current, history)
    assert flagged == {}


def test_detect_drift_skips_metrics_not_in_current() -> None:
    history = [{"faithfulness": 0.90} for _ in range(7)]
    current = {"answer_relevancy": 0.85}  # no faithfulness in current
    flagged = detect_drift(current, history)
    assert "faithfulness" not in flagged


# ---------------------------------------------------------------------------
# load_history
# ---------------------------------------------------------------------------


def test_load_history_reads_jsonl_rows(tmp_path: Path) -> None:
    rows = [
        {"faithfulness": 0.90, "timestamp": "2026-04-09T00:00:00"},
        {"faithfulness": 0.91, "timestamp": "2026-04-10T00:00:00"},
        {"faithfulness": 0.89, "timestamp": "2026-04-11T00:00:00"},
    ]
    p = tmp_path / "drift_history.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    loaded = load_history(p)
    assert len(loaded) == 3
    assert loaded[0]["faithfulness"] == pytest.approx(0.90)


def test_load_history_returns_empty_list_for_missing_file(tmp_path: Path) -> None:
    result = load_history(tmp_path / "no_file.jsonl")
    assert result == []


def test_load_history_respects_max_days(tmp_path: Path) -> None:
    rows = [{"faithfulness": float(i) / 10} for i in range(10)]
    p = tmp_path / "history.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    loaded = load_history(p, max_days=5)
    assert len(loaded) == 5
    # Should be the last 5 rows
    assert loaded[-1]["faithfulness"] == pytest.approx(0.9)
