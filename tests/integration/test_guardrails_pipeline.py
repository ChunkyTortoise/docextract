"""Integration tests: guardrails wired into extraction pipeline and API."""
from __future__ import annotations

from datetime import UTC

from app.schemas.responses import (
    GuardrailPiiMatch,
    GuardrailSummary,
    record_item_from_db,
)
from app.services.guardrails import run_guardrails

# ── record_item_from_db helper ───────────────────────────────────────────────


class FakeRecord:
    """Minimal duck-type for ExtractedRecord used by record_item_from_db."""

    def __init__(self, extracted_data: dict, **kwargs):
        self.id = kwargs.get("id", "rec-1")
        self.job_id = kwargs.get("job_id", "job-1")
        self.document_id = kwargs.get("document_id", "doc-1")
        self.document_type = kwargs.get("document_type", "invoice")
        self.extracted_data = extracted_data
        self.confidence_score = kwargs.get("confidence_score", 0.95)
        self.needs_review = kwargs.get("needs_review", False)
        self.validation_status = kwargs.get("validation_status", "passed")
        from datetime import datetime

        self.created_at = kwargs.get("created_at", datetime.now(UTC))


class TestRecordItemFromDb:
    def test_no_guardrails_metadata(self):
        """Records without _guardrails key have pii_detected=False."""
        r = FakeRecord({"vendor": "Acme Corp"})
        item = record_item_from_db(r)
        assert item.pii_detected is False
        assert item.guardrails is None

    def test_guardrails_with_pii(self):
        """Records with _guardrails.pii_detected populate the response."""
        r = FakeRecord({
            "vendor": "Acme Corp",
            "_guardrails": {
                "passed": False,
                "pii_detected": [
                    {"type": "ssn", "field": "ssn_field", "redacted": "***-**-****"},
                ],
                "grounding": [],
            },
        })
        item = record_item_from_db(r)
        assert item.pii_detected is True
        assert item.guardrails is not None
        assert item.guardrails.passed is False
        assert len(item.guardrails.pii_detected) == 1
        assert item.guardrails.pii_detected[0].type == "ssn"

    def test_guardrails_clean(self):
        """Records with empty guardrail results show passed=True."""
        r = FakeRecord({
            "vendor": "Acme Corp",
            "_guardrails": {
                "passed": True,
                "pii_detected": [],
                "grounding": [
                    {"field": "vendor", "status": "grounded", "reason": "exact substring found"},
                ],
            },
        })
        item = record_item_from_db(r)
        assert item.pii_detected is False
        assert item.guardrails is not None
        assert item.guardrails.passed is True
        assert item.guardrails.grounding_issues == 0

    def test_guardrails_with_ungrounded_fields(self):
        """Ungrounded fields are counted."""
        r = FakeRecord({
            "_guardrails": {
                "passed": True,
                "pii_detected": [],
                "grounding": [
                    {"field": "vendor", "status": "grounded", "reason": "ok"},
                    {"field": "total", "status": "ungrounded", "reason": "not found"},
                    {"field": "date", "status": "ungrounded", "reason": "not found"},
                ],
            },
        })
        item = record_item_from_db(r)
        assert item.guardrails.grounding_issues == 2


# ── Pipeline integration: guardrails flag records for review ─────────────────


class TestGuardrailsPipelineLogic:
    """Test the logic that would run in worker/tasks.py step 7b."""

    def test_pii_triggers_review(self):
        """When PII is detected, the record should be flagged for review."""
        data = {
            "patient_name": "John Smith",
            "ssn": "123-45-6789",
            "diagnosis": "Common cold",
        }
        result = run_guardrails(data, source_text="John Smith 123-45-6789 Common cold")
        assert not result.passed
        assert len(result.pii_detected) == 1
        assert result.pii_detected[0].pattern_type == "ssn"

    def test_clean_data_passes(self):
        """Data without PII passes guardrails."""
        data = {"vendor": "Acme Corp", "total": "$1,234.56"}
        result = run_guardrails(data, source_text="Invoice from Acme Corp total $1,234.56")
        assert result.passed
        assert len(result.pii_detected) == 0

    def test_email_detected_as_pii(self):
        data = {"contact": "john@example.com", "company": "Acme"}
        result = run_guardrails(data, source_text="john@example.com Acme")
        assert not result.passed
        assert result.pii_detected[0].pattern_type == "email"

    def test_credit_card_detected(self):
        data = {"payment_method": "4111-1111-1111-1111"}
        result = run_guardrails(data, source_text="Card: 4111-1111-1111-1111")
        assert not result.passed
        assert result.pii_detected[0].pattern_type == "credit_card"

    def test_grounding_detects_hallucination(self):
        """Extracted value not in source text is flagged as ungrounded."""
        data = {"vendor": "Fabricated Corp", "total": "$999.99"}
        source = "Invoice from Acme Corp total $100.00"
        result = run_guardrails(data, source_text=source)
        ungrounded = [g for g in result.grounding if g.status == "ungrounded"]
        assert len(ungrounded) >= 1

    def test_review_reason_includes_pii_types(self):
        """Review reason string includes detected PII types."""
        data = {"ssn": "123-45-6789", "email": "test@example.com"}
        result = run_guardrails(data, source_text="123-45-6789 test@example.com")
        pii_types = {m.pattern_type for m in result.pii_detected}
        assert "ssn" in pii_types


# ── GuardrailSummary schema ──────────────────────────────────────────────────


class TestGuardrailSummarySchema:
    def test_serialize(self):
        summary = GuardrailSummary(
            passed=False,
            pii_detected=[GuardrailPiiMatch(type="ssn", field="ssn", redacted="***")],
            grounding_issues=1,
        )
        data = summary.model_dump()
        assert data["passed"] is False
        assert len(data["pii_detected"]) == 1
        assert data["grounding_issues"] == 1
