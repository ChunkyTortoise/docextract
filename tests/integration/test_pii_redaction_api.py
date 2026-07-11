"""API-boundary PII redaction: get_record, JSON export, review corrections.

All gated by settings.pii_redaction_enabled (default False). The DB row must
never be mutated by response-side redaction.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

PII_SSN = "123-45-6789"
PII_EMAIL = "jane.doe@example.com"


async def _seed_pii_record(db_session) -> str:
    from app.models.document import Document
    from app.models.job import ExtractionJob
    from app.models.record import ExtractedRecord

    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    record_id = str(uuid.uuid4())
    db_session.add(
        Document(
            id=doc_id,
            original_filename="pii.pdf",
            stored_path=f"documents/{doc_id}/pii.pdf",
            mime_type="application/pdf",
            file_size_bytes=100,
            sha256_hash=uuid.uuid4().hex,
        )
    )
    db_session.add(
        ExtractionJob(
            id=job_id,
            document_id=doc_id,
            status="completed",
            priority="standard",
        )
    )
    db_session.add(
        ExtractedRecord(
            id=record_id,
            job_id=job_id,
            document_id=doc_id,
            document_type="invoice",
            extracted_data={"customer_ssn": PII_SSN, "contact_email": PII_EMAIL},
            raw_text=f"Customer SSN {PII_SSN}",
            confidence_score=0.9,
            needs_review=False,
            validation_status="passed",
            created_at=datetime.now(UTC),
        )
    )
    await db_session.commit()
    return record_id


async def _db_row(db_session, record_id):
    from app.models.record import ExtractedRecord

    result = await db_session.execute(
        select(ExtractedRecord).where(ExtractedRecord.id == record_id)
    )
    return result.scalar_one()


class TestGetRecordBoundary:
    @pytest.mark.asyncio
    async def test_redacts_response_when_enabled(
        self, client, db_session, monkeypatch
    ):
        from app.config import settings

        monkeypatch.setattr(settings, "pii_redaction_enabled", True)
        record_id = await _seed_pii_record(db_session)

        resp = await client.get(f"/api/v1/records/{record_id}")
        assert resp.status_code == 200
        assert PII_SSN not in resp.text
        assert PII_EMAIL not in resp.text
        assert "[SSN]" in resp.text

        # response-side redaction must not dirty the stored row
        row = await _db_row(db_session, record_id)
        assert row.extracted_data["customer_ssn"] == PII_SSN
        assert PII_SSN in row.raw_text

    @pytest.mark.asyncio
    async def test_returns_raw_when_disabled(self, client, db_session, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "pii_redaction_enabled", False)
        record_id = await _seed_pii_record(db_session)

        resp = await client.get(f"/api/v1/records/{record_id}")
        assert resp.status_code == 200
        assert PII_SSN in resp.text


class TestExportBoundary:
    @pytest.mark.asyncio
    async def test_json_export_redacts_when_enabled(
        self, client, db_session, monkeypatch
    ):
        from app.config import settings

        monkeypatch.setattr(settings, "pii_redaction_enabled", True)
        await _seed_pii_record(db_session)

        resp = await client.get("/api/v1/records/export", params={"format": "json"})
        assert resp.status_code == 200
        assert PII_SSN not in resp.text
        assert "[SSN]" in resp.text

    @pytest.mark.asyncio
    async def test_json_export_raw_when_disabled(
        self, client, db_session, monkeypatch
    ):
        from app.config import settings

        monkeypatch.setattr(settings, "pii_redaction_enabled", False)
        await _seed_pii_record(db_session)

        resp = await client.get("/api/v1/records/export", params={"format": "json"})
        assert resp.status_code == 200
        assert PII_SSN in resp.text


class TestReviewCorrectionsBoundary:
    @pytest.mark.asyncio
    async def test_corrections_redacted_before_persistence_when_enabled(
        self, client, db_session, monkeypatch
    ):
        from app.config import settings

        monkeypatch.setattr(settings, "pii_redaction_enabled", True)
        record_id = await _seed_pii_record(db_session)

        resp = await client.patch(
            f"/api/v1/records/{record_id}/review",
            json={
                "decision": "approve",
                "corrections": {"customer_ssn": "999-88-7777"},
                "reviewer_notes": "verified via jane.doe@example.com",
            },
        )
        assert resp.status_code == 200

        row = await _db_row(db_session, record_id)
        assert row.corrected_data["customer_ssn"] == "[SSN]"
        assert PII_EMAIL not in (row.reviewer_notes or "")
        assert "[EMAIL]" in (row.reviewer_notes or "")

    @pytest.mark.asyncio
    async def test_reject_decision_persists_within_status_domain(
        self, client, db_session
    ):
        # decision values are not valid validation_status values; the route
        # must map them or the CHECK constraint rejects the UPDATE.
        record_id = await _seed_pii_record(db_session)

        resp = await client.patch(
            f"/api/v1/records/{record_id}/review",
            json={"decision": "reject"},
        )
        assert resp.status_code == 200

        row = await _db_row(db_session, record_id)
        assert row.validation_status == "failed"
