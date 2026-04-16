"""Unit tests for scripts/eval_gate.py — pure-python logic, no API calls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_gate import (
    ABSOLUTE_FLOORS,
    RELATIVE_DROP_TOLERANCE,
    build_html_report,
    build_pr_comment,
    check_thresholds,
    extract_baseline_metrics,
    extract_judge_metrics,
    extract_promptfoo_metrics,
    extract_ragas_metrics,
    load_json,
)


# ---------------------------------------------------------------------------
# load_json
# ---------------------------------------------------------------------------


def test_load_json_reads_valid_file(tmp_path: Path) -> None:
    data = {"score": 0.9, "count": 28}
    p = tmp_path / "data.json"
    p.write_text(json.dumps(data))
    assert load_json(p) == data


def test_load_json_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert load_json(tmp_path / "nonexistent.json") is None


def test_load_json_returns_none_for_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not valid json {{")
    assert load_json(p) is None


# ---------------------------------------------------------------------------
# extract_promptfoo_metrics
# ---------------------------------------------------------------------------


def test_extract_promptfoo_metrics_valid() -> None:
    data = {"results": {"stats": {"successes": 45, "failures": 5}}}
    result = extract_promptfoo_metrics(data)
    assert result["promptfoo_pass_rate"] == pytest.approx(0.9, abs=1e-4)
    assert result["promptfoo_total"] == 50
    assert result["promptfoo_failures"] == 5


def test_extract_promptfoo_metrics_none_input() -> None:
    assert extract_promptfoo_metrics(None) == {}


def test_extract_promptfoo_metrics_zero_total() -> None:
    data = {"results": {"stats": {"successes": 0, "failures": 0}}}
    assert extract_promptfoo_metrics(data) == {}


# ---------------------------------------------------------------------------
# extract_ragas_metrics
# ---------------------------------------------------------------------------


def test_extract_ragas_metrics_valid() -> None:
    data = {"metrics": {"faithfulness": 0.91, "answer_relevancy": 0.85, "context_precision": 0.78}}
    result = extract_ragas_metrics(data)
    assert result["faithfulness"] == 0.91
    assert result["answer_relevancy"] == 0.85
    assert result["context_precision"] == 0.78


def test_extract_ragas_metrics_none_input() -> None:
    assert extract_ragas_metrics(None) == {}


# ---------------------------------------------------------------------------
# extract_judge_metrics
# ---------------------------------------------------------------------------


def test_extract_judge_metrics_valid() -> None:
    data = {"pass_rate": 0.88, "avg_scores": {"faithfulness": 0.93}, "case_count": 51}
    result = extract_judge_metrics(data)
    assert result["judge_pass_rate"] == 0.88
    assert result["judge_avg_faithfulness"] == 0.93
    assert result["judge_case_count"] == 51


def test_extract_judge_metrics_none_input() -> None:
    assert extract_judge_metrics(None) == {}


# ---------------------------------------------------------------------------
# extract_baseline_metrics
# ---------------------------------------------------------------------------


def test_extract_baseline_metrics_valid() -> None:
    data = {"overall_score": 0.9555, "case_count": 28}
    result = extract_baseline_metrics(data)
    assert result["extraction_f1"] == pytest.approx(0.9555)


def test_extract_baseline_metrics_none_input() -> None:
    assert extract_baseline_metrics(None) == {}


# ---------------------------------------------------------------------------
# check_thresholds
# ---------------------------------------------------------------------------


def test_check_thresholds_all_pass() -> None:
    combined = {
        "faithfulness": 0.91,
        "answer_relevancy": 0.85,
        "context_precision": 0.80,
        "extraction_f1": 0.93,
        "judge_pass_rate": 0.85,
    }
    baseline = {k: v - 0.01 for k, v in combined.items()}  # all improved
    failures = check_thresholds(combined, baseline)
    assert failures == []


def test_check_thresholds_absolute_floor_fail() -> None:
    floor = ABSOLUTE_FLOORS["faithfulness"]
    combined = {"faithfulness": floor - 0.05}  # clearly below floor
    failures = check_thresholds(combined, {})
    assert any(f["metric"] == "faithfulness" for f in failures)


def test_check_thresholds_relative_drop_fail() -> None:
    # Drop > RELATIVE_DROP_TOLERANCE
    baseline = {"faithfulness": 0.90}
    drop_pct = RELATIVE_DROP_TOLERANCE + 0.01
    combined = {"faithfulness": 0.90 * (1 - drop_pct)}
    failures = check_thresholds(combined, baseline)
    assert any(f["metric"] == "faithfulness" for f in failures)


def test_check_thresholds_drop_within_tolerance() -> None:
    baseline = {"faithfulness": 0.90}
    drop_pct = RELATIVE_DROP_TOLERANCE - 0.01
    combined = {"faithfulness": 0.90 * (1 - drop_pct)}
    failures = check_thresholds(combined, baseline)
    # No relative-drop failure; value is still above absolute floor
    assert all(f["metric"] != "faithfulness" for f in failures)


def test_check_thresholds_skips_missing_metrics() -> None:
    # combined has no floats matching any ABSOLUTE_FLOORS key
    combined = {"promptfoo_total": 50}
    failures = check_thresholds(combined, {})
    assert failures == []


# ---------------------------------------------------------------------------
# build_pr_comment
# ---------------------------------------------------------------------------


def test_build_pr_comment_pass() -> None:
    combined = {"faithfulness": 0.91, "answer_relevancy": 0.85}
    baseline = {"faithfulness": 0.89, "answer_relevancy": 0.83}
    comment = build_pr_comment(combined, baseline, failures=[], mode="pull_request")
    assert "PASS" in comment
    assert "Faithfulness" in comment  # build_pr_comment title-cases metric names


def test_build_pr_comment_fail_includes_failures() -> None:
    combined = {"faithfulness": 0.70}
    baseline = {"faithfulness": 0.90}
    failures = [{"metric": "faithfulness", "value": 0.70, "reason": "below absolute floor 0.85"}]
    comment = build_pr_comment(combined, baseline, failures=failures, mode="pull_request")
    assert "FAIL" in comment
    assert "faithfulness" in comment
    assert "below absolute floor" in comment


# ---------------------------------------------------------------------------
# build_html_report
# ---------------------------------------------------------------------------


def test_build_html_report_pass_badge() -> None:
    html = build_html_report({"faithfulness": 0.91}, failures=[])
    assert "PASS" in html
    assert "#2da44e" in html  # green badge color
    assert "faithfulness" in html


def test_build_html_report_fail_badge_and_table() -> None:
    failures = [{"metric": "faithfulness", "value": 0.70, "reason": "below floor"}]
    html = build_html_report({"faithfulness": 0.70}, failures=failures)
    assert "FAIL" in html
    assert "#cf222e" in html  # red badge color
    assert "Threshold Failures" in html
