"""Tests for output guardrails: PII detection and hallucination boundary checking."""
from __future__ import annotations

from app.services.guardrails import (
    GuardrailResult,
    HallucinationChecker,
    PiiDetector,
    PiiMatch,
    run_guardrails,
)

# ── PiiDetector ───────────────────────────────────────────────────────────────


class TestPiiDetectorSsn:
    def test_ssn_detected(self):
        detector = PiiDetector()
        matches = detector.scan({"ssn": "123-45-6789"})
        assert len(matches) == 1
        assert matches[0].pattern_type == "ssn"
        assert matches[0].field_path == "ssn"

    def test_ssn_redacted_replaces_digits(self):
        detector = PiiDetector()
        matches = detector.scan({"field": "SSN: 123-45-6789"})
        assert matches[0].redacted == "SSN: ***-**-****"

    def test_ssn_not_triggered_on_clean_value(self):
        detector = PiiDetector()
        matches = detector.scan({"id": "ABC-DE-FGHI"})
        assert matches == []


class TestPiiDetectorCreditCard:
    def test_credit_card_16_digit_visa(self):
        detector = PiiDetector()
        matches = detector.scan({"card": "4111111111111111"})
        assert len(matches) == 1
        assert matches[0].pattern_type == "credit_card"

    def test_credit_card_space_separated(self):
        detector = PiiDetector()
        matches = detector.scan({"card": "4111 1111 1111 1111"})
        assert len(matches) == 1
        assert matches[0].pattern_type == "credit_card"

    def test_credit_card_dash_separated(self):
        detector = PiiDetector()
        matches = detector.scan({"card": "4111-1111-1111-1111"})
        assert len(matches) == 1
        assert matches[0].pattern_type == "credit_card"

    def test_credit_card_mastercard(self):
        detector = PiiDetector()
        matches = detector.scan({"card": "5500000000000004"})
        assert len(matches) == 1
        assert matches[0].pattern_type == "credit_card"


class TestPiiDetectorPhone:
    def test_phone_dashes(self):
        detector = PiiDetector()
        matches = detector.scan({"phone": "555-867-5309"})
        assert len(matches) == 1
        assert matches[0].pattern_type == "phone"

    def test_phone_parentheses(self):
        detector = PiiDetector()
        matches = detector.scan({"phone": "(555) 867-5309"})
        assert len(matches) == 1
        assert matches[0].pattern_type == "phone"

    def test_phone_international(self):
        detector = PiiDetector()
        matches = detector.scan({"phone": "+1 555 867 5309"})
        assert len(matches) == 1
        assert matches[0].pattern_type == "phone"


class TestPiiDetectorEmail:
    def test_email_detected(self):
        detector = PiiDetector()
        matches = detector.scan({"contact": "user@example.com"})
        assert len(matches) == 1
        assert matches[0].pattern_type == "email"
        assert matches[0].field_path == "contact"

    def test_email_with_plus_addressing(self):
        detector = PiiDetector()
        matches = detector.scan({"email": "user+tag@sub.example.org"})
        assert len(matches) == 1
        assert matches[0].pattern_type == "email"


class TestPiiDetectorCleanData:
    def test_clean_data_no_matches(self):
        detector = PiiDetector()
        matches = detector.scan({
            "vendor": "Acme Corp",
            "total": "1500.00",
            "date": "2026-03-22",
        })
        assert matches == []

    def test_empty_dict_no_matches(self):
        assert PiiDetector().scan({}) == []


class TestPiiDetectorNested:
    def test_nested_dict_pii_found(self):
        detector = PiiDetector()
        matches = detector.scan({"customer": {"ssn": "987-65-4321"}})
        assert len(matches) == 1
        assert matches[0].field_path == "customer.ssn"
        assert matches[0].pattern_type == "ssn"

    def test_list_of_dicts_pii_found(self):
        detector = PiiDetector()
        matches = detector.scan({"contacts": [{"email": "a@b.com"}, {"name": "Bob"}]})
        assert len(matches) == 1
        assert matches[0].field_path == "contacts[0].email"

    def test_list_of_strings_pii_found(self):
        detector = PiiDetector()
        matches = detector.scan({"items": ["clean", "123-45-6789"]})
        assert len(matches) == 1
        assert matches[0].field_path == "items[1]"

    def test_deeply_nested_pii_found(self):
        detector = PiiDetector()
        data = {"level1": {"level2": {"card": "4111111111111111"}}}
        matches = detector.scan(data)
        assert len(matches) == 1
        assert matches[0].field_path == "level1.level2.card"


class TestPiiDetectorEdgeCases:
    def test_multiple_pii_patterns_in_value_only_first_recorded(self):
        # SSN pattern is checked first; only one match per field
        detector = PiiDetector()
        matches = detector.scan({"mixed": "ssn=123-45-6789 email=x@y.com"})
        assert len(matches) == 1
        assert matches[0].pattern_type == "ssn"

    def test_non_string_values_ignored(self):
        detector = PiiDetector()
        matches = detector.scan({"count": 42, "flag": True, "nothing": None})
        assert matches == []


# ── HallucinationChecker ──────────────────────────────────────────────────────


class TestHallucinationCheckerGrounded:
    def test_exact_substring_grounded(self):
        checker = HallucinationChecker()
        results = checker.check({"vendor": "Acme Corp"}, "Invoice from Acme Corp dated 2026-01-01")
        assert results[0].status == "grounded"
        assert results[0].reason == "exact substring found"

    def test_case_insensitive_match(self):
        checker = HallucinationChecker()
        results = checker.check({"vendor": "ACME CORP"}, "invoice from acme corp")
        assert results[0].status == "grounded"

    def test_multiple_fields_all_grounded(self):
        checker = HallucinationChecker()
        source = "Invoice total 500.00 from Globex"
        results = checker.check({"vendor": "Globex", "total": "500.00"}, source)
        statuses = {r.field: r.status for r in results}
        assert statuses["vendor"] == "grounded"
        assert statuses["total"] == "grounded"


class TestHallucinationCheckerPartial:
    def test_high_overlap_partial(self):
        # 4/5 words in source → fraction = 0.8 >= 0.6 → "partial"
        checker = HallucinationChecker()
        source = "The quick brown fox jumps"
        results = checker.check({"sentence": "The quick brown fox leaps"}, source)
        assert results[0].status == "partial"

    def test_partial_reason_includes_word_counts(self):
        checker = HallucinationChecker()
        source = "alpha beta gamma delta"
        results = checker.check({"phrase": "alpha beta gamma delta epsilon"}, source)
        # 4/5 words present → partial
        assert results[0].status == "partial"
        assert "/" in results[0].reason


class TestHallucinationCheckerUngrounded:
    def test_low_overlap_ungrounded(self):
        checker = HallucinationChecker()
        source = "Invoice from Acme Corp"
        results = checker.check({"vendor": "Globex Industries Worldwide"}, source)
        assert results[0].status == "ungrounded"

    def test_zero_overlap_ungrounded(self):
        checker = HallucinationChecker()
        source = "completely different text here"
        results = checker.check({"company": "XYZ Corporation"}, source)
        assert results[0].status == "ungrounded"


class TestHallucinationCheckerSkipped:
    def test_non_string_skipped(self):
        checker = HallucinationChecker()
        results = checker.check({"count": 42}, "source text with count 42")
        assert results[0].status == "skipped"
        assert results[0].field == "count"

    def test_short_value_skipped(self):
        # values with len < 3 skipped
        checker = HallucinationChecker()
        results = checker.check({"abbr": "OK"}, "source text OK yes")
        assert results[0].status == "skipped"

    def test_none_value_skipped(self):
        checker = HallucinationChecker()
        results = checker.check({"field": None}, "source text")
        assert results[0].status == "skipped"

    def test_empty_source_non_string_skipped(self):
        checker = HallucinationChecker()
        results = checker.check({"num": 99, "flag": True}, "")
        assert all(r.status == "skipped" for r in results)

    def test_empty_dict_returns_empty_list(self):
        checker = HallucinationChecker()
        assert checker.check({}, "some source text") == []


# ── run_guardrails ────────────────────────────────────────────────────────────


class TestRunGuardrails:
    def test_clean_extraction_passes(self):
        result = run_guardrails(
            {"vendor": "Acme Corp", "total": "500.00"},
            source_text="Invoice from Acme Corp total 500.00",
        )
        assert result.passed is True
        assert result.pii_detected == []

    def test_pii_in_extraction_fails(self):
        result = run_guardrails(
            {"ssn": "123-45-6789"},
            source_text="document text",
        )
        assert result.passed is False
        assert len(result.pii_detected) == 1

    def test_grounding_check_populates_grounding_list(self):
        result = run_guardrails(
            {"vendor": "Acme Corp"},
            source_text="Invoice from Acme Corp",
            check_pii=False,
        )
        assert len(result.grounding) == 1
        assert result.grounding[0].field == "vendor"

    def test_check_pii_false_skips_pii_scan(self):
        result = run_guardrails(
            {"ssn": "123-45-6789"},
            source_text="document text",
            check_pii=False,
        )
        assert result.pii_detected == []
        assert result.passed is True

    def test_check_grounding_false_skips_grounding(self):
        result = run_guardrails(
            {"vendor": "Acme Corp"},
            source_text="Invoice from Acme Corp",
            check_grounding=False,
        )
        assert result.grounding == []

    def test_empty_source_text_skips_grounding(self):
        result = run_guardrails(
            {"vendor": "Acme Corp"},
            source_text="",
            check_grounding=True,
        )
        assert result.grounding == []

    def test_guardrail_result_passed_false_when_pii_nonempty(self):
        result = GuardrailResult(
            pii_detected=[PiiMatch(pattern_type="ssn", field_path="f", redacted="***")],
            grounding=[],
        )
        assert result.passed is False

    def test_guardrail_result_passed_true_when_no_pii(self):
        result = GuardrailResult(pii_detected=[], grounding=[])
        assert result.passed is True

    def test_both_checks_combined(self):
        result = run_guardrails(
            {"vendor": "Acme Corp", "phone": "555-867-5309"},
            source_text="Call Acme Corp at 555-867-5309",
        )
        assert result.passed is False  # phone is PII
        assert len(result.pii_detected) == 1
        assert result.pii_detected[0].pattern_type == "phone"
        # grounding should still be populated
        assert len(result.grounding) > 0
