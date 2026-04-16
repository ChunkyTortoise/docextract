"""Tests for SROIE benchmark scoring logic."""
from __future__ import annotations


class TestNormalizeText:
    def test_lowercases(self):
        from scripts.benchmark_sroie import normalize_text
        assert normalize_text("HELLO WORLD") == "hello world"

    def test_strips_whitespace(self):
        from scripts.benchmark_sroie import normalize_text
        assert normalize_text("  hello  world  ") == "hello world"

    def test_none_returns_empty(self):
        from scripts.benchmark_sroie import normalize_text
        assert normalize_text(None) == ""

    def test_empty_returns_empty(self):
        from scripts.benchmark_sroie import normalize_text
        assert normalize_text("") == ""


class TestTokenF1:
    def test_exact_match(self):
        from scripts.benchmark_sroie import compute_token_f1
        p, r, f1 = compute_token_f1("hello world", "hello world")
        assert f1 == 1.0
        assert p == 1.0
        assert r == 1.0

    def test_no_overlap(self):
        from scripts.benchmark_sroie import compute_token_f1
        p, r, f1 = compute_token_f1("apple orange", "banana grape")
        assert f1 == 0.0

    def test_partial_overlap(self):
        from scripts.benchmark_sroie import compute_token_f1
        _, _, f1 = compute_token_f1("hello world extra", "hello world")
        assert 0 < f1 < 1.0

    def test_both_empty(self):
        from scripts.benchmark_sroie import compute_token_f1
        p, r, f1 = compute_token_f1("", "")
        assert f1 == 1.0

    def test_predicted_empty_gt_nonempty(self):
        from scripts.benchmark_sroie import compute_token_f1
        p, r, f1 = compute_token_f1("", "some text")
        assert f1 == 0.0

    def test_gt_empty_predicted_nonempty(self):
        from scripts.benchmark_sroie import compute_token_f1
        p, r, f1 = compute_token_f1("some text", "")
        assert f1 == 0.0


class TestFieldScore:
    def test_precision_zero_when_no_tp(self):
        from scripts.benchmark_sroie import FieldScore
        s = FieldScore(field="total")
        assert s.precision == 0.0

    def test_f1_zero_when_no_matches(self):
        from scripts.benchmark_sroie import FieldScore
        s = FieldScore(field="company")
        assert s.f1 == 0.0

    def test_exact_match_accuracy(self):
        from scripts.benchmark_sroie import FieldScore
        s = FieldScore(field="date", exact_matches=3, total=4)
        assert s.exact_match_accuracy == 0.75

    def test_exact_match_accuracy_zero_total(self):
        from scripts.benchmark_sroie import FieldScore
        s = FieldScore(field="date")
        assert s.exact_match_accuracy == 0.0


class TestScoreSingleDocument:
    def test_perfect_prediction_updates_scores(self):
        from scripts.benchmark_sroie import score_single_document
        field_scores: dict = {}
        score_single_document(
            {"company": "ACME", "date": "2024-01-01", "address": "123 Main St", "total": "50.00"},
            {"company": "ACME", "date": "2024-01-01", "address": "123 Main St", "total": "50.00"},
            field_scores,
        )
        assert field_scores["company"].exact_matches == 1
        assert field_scores["total"].exact_matches == 1

    def test_missed_field_reduces_score(self):
        from scripts.benchmark_sroie import score_single_document
        field_scores: dict = {}
        score_single_document(
            {"company": None, "date": "2024-01-01", "address": "123 Main", "total": "50"},
            {"company": "ACME", "date": "2024-01-01", "address": "123 Main", "total": "50"},
            field_scores,
        )
        assert field_scores["company"].exact_matches == 0
        assert field_scores["date"].exact_matches == 1


class TestRunDryRun:
    def test_dry_run_returns_results(self):
        from scripts.benchmark_sroie import run_dry_run
        results = run_dry_run()
        assert results.total_documents == 3
        assert "company" in results.field_scores
        assert "total" in results.field_scores

    def test_dry_run_macro_f1_positive(self):
        from scripts.benchmark_sroie import run_dry_run
        results = run_dry_run()
        assert results.macro_f1 > 0.0

    def test_dry_run_confidence_scores_present(self):
        from scripts.benchmark_sroie import run_dry_run
        results = run_dry_run()
        assert len(results.confidence_scores) == 3


class TestBenchmarkResultsTable:
    def test_format_table_has_headers(self):
        from scripts.benchmark_sroie import format_results_table, run_dry_run
        results = run_dry_run()
        table = format_results_table(results)
        assert "SROIE Benchmark" in table
        assert "company" in table
        assert "total" in table
        assert "F1" in table


class TestMainDryRun:
    def test_main_dry_run_exits_zero(self):
        from scripts.benchmark_sroie import main
        result = main(["--dry-run"])
        assert result == 0

    def test_main_no_args_exits_nonzero(self):
        from scripts.benchmark_sroie import main
        result = main([])
        assert result == 1
