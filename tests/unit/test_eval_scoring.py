"""Tests for autoresearch eval scoring logic — no API calls."""
from __future__ import annotations

import pytest

from autoresearch.eval import (
    _levenshtein,
    _score_list,
    _score_list_item,
    _score_scalar,
    _string_similarity,
    load_dataset,
    score_extraction,
)

# ---------------------------------------------------------------------------
# _levenshtein
# ---------------------------------------------------------------------------

class TestLevenshtein:
    def test_identical(self):
        assert _levenshtein("abc", "abc") == 0

    def test_empty_a(self):
        assert _levenshtein("", "abc") == 3

    def test_empty_b(self):
        assert _levenshtein("abc", "") == 3

    def test_both_empty(self):
        assert _levenshtein("", "") == 0

    def test_one_edit(self):
        assert _levenshtein("abc", "abd") == 1

    def test_insertion(self):
        assert _levenshtein("ab", "abc") == 1

    def test_deletion(self):
        assert _levenshtein("abc", "ab") == 1


# ---------------------------------------------------------------------------
# _string_similarity
# ---------------------------------------------------------------------------

class TestStringSimilarity:
    def test_identical(self):
        assert _string_similarity("hello", "hello") == 1.0

    def test_both_empty(self):
        assert _string_similarity("", "") == 1.0

    def test_completely_different(self):
        sim = _string_similarity("abc", "xyz")
        assert 0.0 <= sim < 1.0

    def test_partial_match(self):
        sim = _string_similarity("invoice", "Invoice")
        # Case difference = 1 edit out of 7
        assert sim == pytest.approx(1.0 - 1 / 7, abs=1e-6)


# ---------------------------------------------------------------------------
# _score_scalar
# ---------------------------------------------------------------------------

class TestScoreScalar:
    def test_null_expected_null_extracted(self):
        assert _score_scalar(None, None) == 1.0

    def test_null_extracted_non_null_expected(self):
        assert _score_scalar(None, "something") == 0.0

    def test_null_expected_non_null_extracted(self):
        # partial credit when expected is null
        assert _score_scalar("extra", None) == 0.5

    def test_exact_numeric_match(self):
        assert _score_scalar(1080.0, 1080.0) == 1.0

    def test_numeric_within_1_percent(self):
        assert _score_scalar(1079.5, 1080.0) == 1.0

    def test_numeric_beyond_1_percent(self):
        assert _score_scalar(900.0, 1080.0) == 0.0

    def test_numeric_as_string_extracted(self):
        assert _score_scalar("1080.0", 1080.0) == 1.0

    def test_exact_string_match(self):
        assert _score_scalar("INV-001", "INV-001") == 1.0

    def test_partial_string_match(self):
        score = _score_scalar("INV-001-A", "INV-001")
        assert 0.0 < score < 1.0

    def test_zero_numeric_match(self):
        assert _score_scalar(0.0, 0) == 1.0

    def test_zero_numeric_mismatch(self):
        assert _score_scalar(5.0, 0) == 0.0


# ---------------------------------------------------------------------------
# _score_list_item
# ---------------------------------------------------------------------------

class TestScoreListItem:
    def test_perfect_match(self):
        item = {"description": "Widget", "quantity": 2.0, "unit_price": 50.0, "total": 100.0}
        assert _score_list_item(item, item) == 1.0

    def test_empty_expected(self):
        assert _score_list_item({}, {}) == 1.0

    def test_partial_match(self):
        expected = {"description": "Widget", "quantity": 2.0, "total": 100.0}
        extracted = {"description": "Widget", "quantity": 2.0, "total": 50.0}  # wrong total
        score = _score_list_item(extracted, expected)
        assert 0.0 < score < 1.0

    def test_null_values_in_expected_skipped(self):
        expected = {"description": "Widget", "sku": None}
        extracted = {"description": "Widget"}
        # Only non-null expected fields scored
        assert _score_list_item(extracted, expected) == 1.0


# ---------------------------------------------------------------------------
# _score_list
# ---------------------------------------------------------------------------

class TestScoreList:
    def test_empty_expected(self):
        assert _score_list([], []) == 1.0

    def test_no_extracted(self):
        assert _score_list(None, [{"description": "x"}]) == 0.0

    def test_perfect_match_ordered(self):
        items = [{"description": "A", "total": 10.0}, {"description": "B", "total": 20.0}]
        assert _score_list(items, items) == 1.0

    def test_best_pair_unordered(self):
        expected = [{"description": "A"}, {"description": "B"}]
        extracted = [{"description": "B"}, {"description": "A"}]
        score = _score_list(extracted, expected)
        assert score == 1.0

    def test_partial_list(self):
        expected = [{"description": "A"}, {"description": "B"}]
        extracted = [{"description": "A"}]
        score = _score_list(extracted, expected)
        # B maps to best available (A with low similarity), A maps to A perfectly
        assert 0.0 < score < 1.0


# ---------------------------------------------------------------------------
# score_extraction
# ---------------------------------------------------------------------------

class TestScoreExtraction:
    def test_perfect_extraction(self):
        expected = {"invoice_number": "INV-001", "total_amount": 500.0}
        critical = ["invoice_number", "total_amount"]
        score = score_extraction(expected, expected, critical)
        assert score == 1.0

    def test_all_null(self):
        expected = {"invoice_number": "INV-001", "total_amount": 500.0}
        critical = ["invoice_number", "total_amount"]
        score = score_extraction({}, expected, critical)
        assert score == 0.0

    def test_critical_fields_weighted_more(self):
        expected = {"invoice_number": "INV-001", "notes": "some notes"}
        # Perfect critical, wrong non-critical
        extracted_good_critical = {"invoice_number": "INV-001", "notes": "completely wrong"}
        extracted_bad_critical = {"invoice_number": "WRONG", "notes": "some notes"}
        critical = ["invoice_number"]
        score_good = score_extraction(extracted_good_critical, expected, critical)
        score_bad = score_extraction(extracted_bad_critical, expected, critical)
        assert score_good > score_bad

    def test_list_field_scored(self):
        expected = {
            "line_items": [
                {"description": "Widget", "total": 100.0}
            ]
        }
        extracted = {
            "line_items": [
                {"description": "Widget", "total": 100.0}
            ]
        }
        score = score_extraction(extracted, expected, [])
        assert score == 1.0

    def test_missing_list_field(self):
        expected = {"line_items": [{"description": "Widget"}]}
        score = score_extraction({}, expected, [])
        assert score == 0.0

    def test_empty_extraction_empty_expected(self):
        score = score_extraction({}, {}, [])
        assert score == 0.0


# ---------------------------------------------------------------------------
# load_dataset
# ---------------------------------------------------------------------------

class TestLoadDataset:
    def test_loads_at_least_16_cases(self):
        dataset = load_dataset()
        assert len(dataset) >= 16

    def test_all_cases_have_required_fields(self):
        dataset = load_dataset()
        for case in dataset:
            assert "id" in case
            assert "doc_type" in case
            assert "input_text" in case
            assert "expected" in case
            assert "critical_fields" in case
            assert "weight" in case

    def test_doc_types_are_valid(self):
        valid_types = {"invoice", "receipt", "purchase_order", "bank_statement", "medical_record", "identity_document"}
        dataset = load_dataset()
        for case in dataset:
            assert case["doc_type"] in valid_types

    def test_expected_fields_match_schemas(self):
        """Spot-check that expected field names match Pydantic schema field names."""
        dataset = load_dataset()
        invoice_cases = [c for c in dataset if c["doc_type"] == "invoice"]
        assert len(invoice_cases) >= 1
        inv = invoice_cases[0]["expected"]
        # InvoiceSchema field names (not bill_to_name, not tax_total)
        assert "customer_name" in inv
        assert "tax_amount" in inv
        assert "total_amount" in inv
        assert "bill_to_name" not in inv
        assert "tax_total" not in inv

    def test_critical_fields_are_subsets_of_expected(self):
        dataset = load_dataset()
        for case in dataset:
            for field in case["critical_fields"]:
                assert field in case["expected"], (
                    f"Case {case['id']}: critical field {field!r} not in expected"
                )
