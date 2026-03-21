"""Tests for eval reporter."""
from __future__ import annotations

import json
import pytest

from autoresearch.eval import CaseResult
from autoresearch.reporter import generate_report, compare_runs


def _make_results(n: int = 3) -> list[CaseResult]:
    return [
        CaseResult(
            case_id=f"case_{i:02d}",
            doc_type="invoice",
            score=0.7 + i * 0.05,
            weight=1.0,
            completeness=0.8,
            hallucination_count=0,
            format_valid=True,
        )
        for i in range(n)
    ]


class TestGenerateReport:
    def test_json_format_default(self):
        results = _make_results()
        report = generate_report(results, 0.75)
        data = json.loads(report)
        assert "overall_score" in data
        assert data["overall_score"] == 0.75

    def test_json_format_explicit(self):
        results = _make_results()
        report = generate_report(results, 0.75, format="json")
        data = json.loads(report)
        assert data["case_count"] == 3

    def test_json_cases_list(self):
        results = _make_results(2)
        report = generate_report(results, 0.80, format="json")
        data = json.loads(report)
        assert len(data["cases"]) == 2
        assert "score" in data["cases"][0]

    def test_markdown_format(self):
        results = _make_results()
        report = generate_report(results, 0.75, format="markdown")
        assert "# Eval Report" in report
        assert "0.7500" in report

    def test_markdown_has_table(self):
        results = _make_results()
        report = generate_report(results, 0.75, format="markdown")
        assert "| Case ID |" in report
        assert "case_00" in report

    def test_empty_results(self):
        report = generate_report([], 0.0, format="json")
        data = json.loads(report)
        assert data["case_count"] == 0
        assert data["cases"] == []


class TestCompareRuns:
    def test_returns_string(self):
        results = _make_results()
        output = compare_runs(results, 0.70)
        assert isinstance(output, str)

    def test_contains_delta(self):
        results = _make_results()
        # results avg score > 0.70 so delta should be positive
        output = compare_runs(results, 0.70)
        assert "Delta" in output or "delta" in output.lower() or "+" in output

    def test_contains_per_case_table(self):
        results = _make_results(2)
        output = compare_runs(results, 0.70)
        assert "case_00" in output

    def test_empty_results_returns_message(self):
        output = compare_runs([], 0.70)
        assert "No results" in output

    def test_improvement_shows_positive_delta(self):
        results = [CaseResult("c", "invoice", 1.0, 1.0, 1.0, 0, True)]
        output = compare_runs(results, 0.5)
        assert "+" in output
