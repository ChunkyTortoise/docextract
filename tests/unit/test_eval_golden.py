"""Tests for golden-fixture-based eval — no API calls."""
from __future__ import annotations

import pytest

from autoresearch.eval import (
    CaseResult,
    detect_hallucinations,
    load_dataset,
    run_eval,
    score_completeness,
    validate_response_format,
)
from autoresearch.fixtures import list_golden_cases, load_golden_response


class TestLoadGoldenResponse:
    def test_returns_dict_for_existing_case(self):
        result = load_golden_response("invoice_01")
        assert result is not None
        assert isinstance(result, dict)

    def test_returns_none_for_missing_case(self):
        result = load_golden_response("nonexistent_case_xyz")
        assert result is None

    def test_golden_has_required_fields(self):
        result = load_golden_response("invoice_01")
        assert "case_id" in result
        assert "model" in result
        assert "recorded_at" in result
        assert "parsed_extraction" in result

    def test_case_id_matches_filename(self):
        result = load_golden_response("receipt_01")
        assert result["case_id"] == "receipt_01"

    def test_parsed_extraction_is_dict(self):
        result = load_golden_response("invoice_01")
        assert isinstance(result["parsed_extraction"], dict)


class TestListGoldenCases:
    def test_returns_list(self):
        cases = list_golden_cases()
        assert isinstance(cases, list)

    def test_returns_at_least_16_cases(self):
        cases = list_golden_cases()
        assert len(cases) >= 16

    def test_all_dataset_cases_have_golden(self):
        from autoresearch.eval import load_dataset
        dataset = load_dataset()
        golden_cases = set(list_golden_cases())
        for case in dataset:
            assert case["id"] in golden_cases, f"Missing golden for {case['id']}"

    def test_sorted_alphabetically(self):
        cases = list_golden_cases()
        assert cases == sorted(cases)


class TestScoreCompleteness:
    def test_perfect_completeness(self):
        expected = {"a": "x", "b": 1.0}
        extracted = {"a": "x", "b": 1.0}
        assert score_completeness(extracted, expected) == 1.0

    def test_zero_completeness(self):
        expected = {"a": "x", "b": 1.0}
        extracted = {}
        assert score_completeness(extracted, expected) == 0.0

    def test_half_completeness(self):
        expected = {"a": "x", "b": "y"}
        extracted = {"a": "x"}
        assert score_completeness(extracted, expected) == 0.5

    def test_null_expected_fields_excluded(self):
        # Null expected fields don't count
        expected = {"a": "x", "b": None}
        extracted = {"a": "x"}
        assert score_completeness(extracted, expected) == 1.0

    def test_empty_expected_returns_1(self):
        assert score_completeness({}, {}) == 1.0

    def test_list_fields_counted(self):
        expected = {"items": [{"a": 1}], "total": 10.0}
        extracted = {"items": [{"a": 1}], "total": 10.0}
        assert score_completeness(extracted, expected) == 1.0


class TestDetectHallucinations:
    def test_no_hallucinations_when_matches_expected(self):
        extracted = {"vendor_name": "Acme Corp"}
        expected = {"vendor_name": "Acme Corp"}
        result = detect_hallucinations(extracted, expected, "Acme Corp invoice")
        assert result == []

    def test_no_hallucination_when_in_input_text(self):
        extracted = {"vendor_name": "Acme Corp"}
        expected = {"vendor_name": "something else"}
        result = detect_hallucinations(extracted, expected, "Invoice from Acme Corp")
        assert "vendor_name" not in result

    def test_null_values_not_hallucinations(self):
        extracted = {"vendor_name": None, "total": None}
        expected = {}
        result = detect_hallucinations(extracted, expected, "some text")
        assert result == []

    def test_list_values_not_checked(self):
        extracted = {"line_items": [{"desc": "Widget"}]}
        expected = {}
        result = detect_hallucinations(extracted, expected, "some text")
        assert "line_items" not in result

    def test_returns_list_type(self):
        result = detect_hallucinations({}, {}, "text")
        assert isinstance(result, list)


class TestValidateResponseFormat:
    def test_valid_invoice(self):
        data = {"invoice_number": "INV-001", "total_amount": 100.0}
        assert validate_response_format(data, "invoice") is True

    def test_valid_receipt(self):
        data = {"merchant_name": "Coffee Shop", "total": 5.50}
        assert validate_response_format(data, "receipt") is True

    def test_unknown_doc_type_returns_true(self):
        assert validate_response_format({}, "unknown") is True

    def test_empty_dict_valid_for_invoice(self):
        # All fields are Optional so empty dict is valid
        assert validate_response_format({}, "invoice") is True

    def test_valid_medical_record(self):
        data = {"patient_name": "John Doe", "visit_date": "2024-01-01"}
        assert validate_response_format(data, "medical_record") is True

    def test_valid_bank_statement(self):
        data = {"account_holder": "Jane Smith", "closing_balance": 1000.0}
        assert validate_response_format(data, "bank_statement") is True


class TestCaseResultDataclass:
    def test_case_result_fields(self):
        result = CaseResult(
            case_id="test_01",
            doc_type="invoice",
            score=0.85,
            weight=1.0,
            completeness=0.9,
            hallucination_count=1,
            format_valid=True,
        )
        assert result.case_id == "test_01"
        assert result.score == 0.85
        assert result.hallucination_count == 1
        assert result.format_valid is True


@pytest.mark.asyncio
class TestRunEvalGoldenMode:
    async def test_golden_mode_returns_tuple(self):
        dataset = load_dataset()
        result = await run_eval(dataset, golden=True)
        assert isinstance(result, tuple)
        assert len(result) == 2

    async def test_golden_mode_returns_score_and_results(self):
        dataset = load_dataset()
        score, case_results = await run_eval(dataset, golden=True)
        assert isinstance(score, float)
        assert isinstance(case_results, list)

    async def test_golden_mode_score_between_0_and_1(self):
        dataset = load_dataset()
        score, _ = await run_eval(dataset, golden=True)
        assert 0.0 <= score <= 1.0

    async def test_golden_mode_returns_case_results_for_all_cases(self):
        dataset = load_dataset()
        _, case_results = await run_eval(dataset, golden=True)
        assert len(case_results) == len(dataset)

    async def test_dry_run_returns_tuple(self):
        dataset = load_dataset()[:2]  # Just 2 cases for speed
        result = await run_eval(dataset, dry_run=True)
        assert isinstance(result, tuple)

    async def test_case_results_have_completeness(self):
        dataset = load_dataset()[:1]
        _, case_results = await run_eval(dataset, dry_run=True)
        assert hasattr(case_results[0], 'completeness')

    async def test_case_results_have_format_valid(self):
        dataset = load_dataset()[:1]
        _, case_results = await run_eval(dataset, dry_run=True)
        assert hasattr(case_results[0], 'format_valid')
