"""PII redaction at persistence and response boundaries.

The trace sanitizer (sanitize_for_trace) has always scrubbed observability
exports; these tests cover the redact_pii boundary function and the
response-schema boundary (record_item_from_db), both gated by
settings.pii_redaction_enabled.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "adversarial" / "pii_medical_invoice.json"
)


@pytest.fixture
def pii_payload() -> dict:
    return json.loads(FIXTURE.read_text())


class TestRedactPii:
    def test_redacts_all_pattern_types_in_nested_data(self, pii_payload):
        from app.services.pii_sanitizer import redact_pii

        clean = redact_pii(pii_payload)
        blob = json.dumps(clean)
        assert "123-45-6789" not in blob
        assert "4111 1111 1111 1111" not in blob
        assert "jane.doe@example.com" not in blob
        assert "555-867-5309" not in blob
        assert "[SSN]" in blob
        assert "[CC]" in blob
        assert "[EMAIL]" in blob
        assert "[PHONE]" in blob

    def test_does_not_mutate_input(self, pii_payload):
        from app.services.pii_sanitizer import redact_pii

        before = json.dumps(pii_payload, sort_keys=True)
        redact_pii(pii_payload)
        assert json.dumps(pii_payload, sort_keys=True) == before

    def test_preserves_non_pii_values(self, pii_payload):
        from app.services.pii_sanitizer import redact_pii

        clean = redact_pii(pii_payload)
        assert clean["invoice_number"] == "INV-2001"
        assert clean["total_amount"] == 250.0
        assert clean["line_items"][0]["amount"] == 250.0

    def test_redacts_plain_strings(self):
        from app.services.pii_sanitizer import redact_pii

        assert redact_pii("SSN is 123-45-6789") == "SSN is [SSN]"


def _fake_record(extracted_data: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id="rec-1",
        job_id="job-1",
        document_id="doc-1",
        document_type="invoice",
        extracted_data=extracted_data,
        confidence_score=0.9,
        needs_review=False,
        validation_status="passed",
        created_at=datetime.now(UTC),
    )


class TestRecordItemResponseBoundary:
    def test_redacts_extracted_data_when_flag_enabled(
        self, pii_payload, monkeypatch
    ):
        from app.config import settings
        from app.schemas.responses import record_item_from_db

        monkeypatch.setattr(settings, "pii_redaction_enabled", True)
        record = _fake_record(pii_payload)
        item = record_item_from_db(record)
        blob = json.dumps(item.extracted_data)
        assert "123-45-6789" not in blob
        assert "[SSN]" in blob
        # the DB object itself must stay untouched
        assert record.extracted_data["patient_ssn"] == "123-45-6789"

    def test_passes_data_through_when_flag_disabled(
        self, pii_payload, monkeypatch
    ):
        from app.config import settings
        from app.schemas.responses import record_item_from_db

        monkeypatch.setattr(settings, "pii_redaction_enabled", False)
        item = record_item_from_db(_fake_record(pii_payload))
        assert item.extracted_data["patient_ssn"] == "123-45-6789"

    def test_redacts_guardrail_pii_previews_when_flag_enabled(self, monkeypatch):
        # Guardrail previews mask digits only, so email previews carry the
        # full address; the response boundary must redact them too.
        from app.config import settings
        from app.schemas.responses import record_item_from_db

        monkeypatch.setattr(settings, "pii_redaction_enabled", True)
        record = _fake_record(
            {
                "contact_email": "jane.doe@example.com",
                "_guardrails": {
                    "passed": False,
                    "pii_detected": [
                        {
                            "type": "email",
                            "field": "contact_email",
                            "redacted": "jane.doe@example.com",
                        }
                    ],
                    "grounding": [],
                },
            }
        )
        item = record_item_from_db(record)
        assert item.guardrails is not None
        assert item.guardrails.pii_detected[0].redacted == "[EMAIL]"
        # the DB object itself must stay untouched
        assert (
            record.extracted_data["_guardrails"]["pii_detected"][0]["redacted"]
            == "jane.doe@example.com"
        )
