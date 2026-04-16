"""Tests for scripts/run_eval_ci — CI regression gate."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Allow imports from repo root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from autoresearch.eval import CaseResult
from scripts.run_eval_ci import (
    REGRESSION_TOLERANCE,
    build_markdown_summary,
    check_regression,
    load_baseline,
    save_baseline,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_results(score: float, n: int = 4) -> list[CaseResult]:
    """Create a list of CaseResult with a uniform score."""
    return [
        CaseResult(
            case_id=f"case_{i}",
            doc_type="invoice",
            score=score,
            weight=1.0,
            completeness=score,
            hallucination_count=0,
            format_valid=True,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# load_baseline / save_baseline
# ---------------------------------------------------------------------------

class TestLoadBaseline:
    def test_loads_existing_baseline(self, tmp_path):
        baseline_file = tmp_path / "baseline.json"
        baseline_file.write_text(json.dumps({"overall_score": 0.85, "case_count": 16}))
        baseline = load_baseline(baseline_file)
        assert baseline["overall_score"] == pytest.approx(0.85)
        assert baseline["case_count"] == 16

    def test_returns_none_for_missing_file(self, tmp_path):
        baseline = load_baseline(tmp_path / "nonexistent.json")
        assert baseline is None

    def test_returns_none_for_invalid_json(self, tmp_path):
        bad_file = tmp_path / "baseline.json"
        bad_file.write_text("not json {{{")
        baseline = load_baseline(bad_file)
        assert baseline is None


class TestSaveBaseline:
    def test_saves_score_and_case_count(self, tmp_path):
        results = _make_results(0.90, n=8)
        path = tmp_path / "baseline.json"
        save_baseline(0.90, results, path)
        data = json.loads(path.read_text())
        assert data["overall_score"] == pytest.approx(0.90)
        assert data["case_count"] == 8
        assert "timestamp" in data

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "baseline.json"
        save_baseline(0.80, _make_results(0.80), path)
        assert path.exists()


# ---------------------------------------------------------------------------
# check_regression
# ---------------------------------------------------------------------------

class TestCheckRegression:
    def test_passes_when_score_above_baseline(self):
        passed, delta = check_regression(current_score=0.90, baseline_score=0.85)
        assert passed is True
        assert delta == pytest.approx(0.05)

    def test_passes_when_score_equals_baseline(self):
        passed, delta = check_regression(current_score=0.85, baseline_score=0.85)
        assert passed is True
        assert delta == pytest.approx(0.0)

    def test_passes_within_tolerance(self):
        # Drops by exactly REGRESSION_TOLERANCE — should still pass
        passed, delta = check_regression(
            current_score=0.85 - REGRESSION_TOLERANCE,
            baseline_score=0.85,
        )
        assert passed is True

    def test_fails_beyond_tolerance(self):
        # Drops by REGRESSION_TOLERANCE + 0.001
        passed, delta = check_regression(
            current_score=0.85 - REGRESSION_TOLERANCE - 0.001,
            baseline_score=0.85,
        )
        assert passed is False
        assert delta < 0

    def test_passes_when_no_baseline(self):
        # First run with no baseline always passes
        passed, delta = check_regression(current_score=0.75, baseline_score=None)
        assert passed is True
        assert delta == 0.0


# ---------------------------------------------------------------------------
# build_markdown_summary
# ---------------------------------------------------------------------------

class TestBuildMarkdownSummary:
    def test_contains_overall_score(self):
        results = _make_results(0.88)
        md = build_markdown_summary(
            overall_score=0.88,
            case_results=results,
            baseline_score=0.85,
            passed=True,
        )
        assert "0.88" in md or "0.880" in md

    def test_contains_pass_status(self):
        results = _make_results(0.88)
        md = build_markdown_summary(0.88, results, 0.85, passed=True)
        assert "PASS" in md or "pass" in md.lower() or "✅" in md

    def test_contains_fail_status(self):
        results = _make_results(0.70)
        md = build_markdown_summary(0.70, results, 0.85, passed=False)
        assert "FAIL" in md or "fail" in md.lower() or "❌" in md

    def test_contains_delta(self):
        results = _make_results(0.88)
        md = build_markdown_summary(0.88, results, 0.85, passed=True)
        # Should show delta somewhere
        assert "+0.03" in md or "+0.030" in md or "0.030" in md

    def test_contains_per_doc_type_row(self):
        results = _make_results(0.88)
        md = build_markdown_summary(0.88, results, 0.85, passed=True)
        assert "invoice" in md

    def test_no_baseline_shows_first_run(self):
        results = _make_results(0.80)
        md = build_markdown_summary(0.80, results, baseline_score=None, passed=True)
        assert "first run" in md.lower() or "no baseline" in md.lower() or "N/A" in md
