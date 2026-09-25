from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import APIKey
from app.models.document import Document
from app.models.job import ExtractionJob
from app.models.record import ExtractedRecord
from app.utils.hashing import hash_api_key


async def _seed_key(db: AsyncSession, raw_key: str, role: str) -> None:
    key_hash = hash_api_key(raw_key)
    existing = await db.execute(select(APIKey).where(APIKey.key_hash == key_hash))
    if existing.scalar_one_or_none() is None:
        db.add(
            APIKey(
                id=str(uuid.uuid4()),
                name=f"{role}-key",
                role=role,
                key_hash=key_hash,
                is_active=True,
                rate_limit_per_minute=1000,
            )
        )
        await db.commit()


async def _seed_review_item(db: AsyncSession) -> str:
    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    record_id = str(uuid.uuid4())
    db.add(
        Document(
            id=doc_id,
            original_filename="review.pdf",
            stored_path=f"documents/{doc_id}/review.pdf",
            mime_type="application/pdf",
            file_size_bytes=100,
            sha256_hash=uuid.uuid4().hex,
        )
    )
    db.add(
        ExtractionJob(
            id=job_id,
            document_id=doc_id,
            status="needs_review",
            priority="standard",
        )
    )
    db.add(
        ExtractedRecord(
            id=record_id,
            job_id=job_id,
            document_id=doc_id,
            document_type="invoice",
            extracted_data={"invoice_number": "A1"},
            confidence_score=0.5,
            needs_review=True,
            validation_status="pending_review",
        )
    )
    await db.commit()
    return record_id


@pytest.mark.asyncio
async def test_viewer_forbidden_on_review_and_report_generate(client: AsyncClient, db_session: AsyncSession):
    viewer_key = "dex_viewer_authz_001"
    await _seed_key(db_session, viewer_key, "viewer")
    record_id = await _seed_review_item(db_session)

    review_resp = await client.get("/api/v1/review/metrics", headers={"X-API-Key": viewer_key})
    assert review_resp.status_code == 403

    claim_resp = await client.post(f"/api/v1/review/items/{record_id}/claim", headers={"X-API-Key": viewer_key})
    assert claim_resp.status_code == 403

    generate_resp = await client.post(
        "/api/v1/reports/generate",
        json={"format": "json"},
        headers={"X-API-Key": viewer_key},
    )
    assert generate_resp.status_code == 403

    list_resp = await client.get("/api/v1/reports", headers={"X-API-Key": viewer_key})
    assert list_resp.status_code == 200


@pytest.mark.asyncio
async def test_operator_allowed_for_review_and_report_generate(client: AsyncClient, db_session: AsyncSession):
    operator_key = "dex_operator_authz_001"
    await _seed_key(db_session, operator_key, "operator")
    record_id = await _seed_review_item(db_session)

    metrics_resp = await client.get("/api/v1/review/metrics", headers={"X-API-Key": operator_key})
    assert metrics_resp.status_code == 200

    claim_resp = await client.post(f"/api/v1/review/items/{record_id}/claim", headers={"X-API-Key": operator_key})
    assert claim_resp.status_code == 200

    generate_resp = await client.post(
        "/api/v1/reports/generate",
        json={"format": "json"},
        headers={"X-API-Key": operator_key},
    )
    assert generate_resp.status_code == 200
    report_id = generate_resp.json()["report_id"]

    get_resp = await client.get(f"/api/v1/reports/{report_id}", headers={"X-API-Key": operator_key})
    assert get_resp.status_code == 200


@pytest.mark.asyncio
async def test_viewer_can_read_roi_summary(client: AsyncClient, db_session: AsyncSession):
    viewer_key = "dex_viewer_authz_002"
    await _seed_key(db_session, viewer_key, "viewer")

    resp = await client.get("/api/v1/roi/summary", headers={"X-API-Key": viewer_key})
    assert resp.status_code == 200
    assert "kpis" in resp.json()


@pytest.mark.asyncio
async def test_viewer_denied_on_every_write_route(client: AsyncClient, db_session: AsyncSession):
    """Viewer keys get 403 on every state-changing route (lane B P0 matrix):
    upload, batch, delete, cancel, record review/approve, feedback, webhook test."""
    viewer_key = "dex_viewer_authz_003"
    await _seed_key(db_session, viewer_key, "viewer")
    headers = {"X-API-Key": viewer_key}

    upload = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("viewer.pdf", b"%PDF-1.4 test", "application/pdf")},
        headers=headers,
    )
    assert upload.status_code == 403

    batch = await client.post(
        "/api/v1/documents/batch",
        files=[("files", ("viewer.pdf", b"%PDF-1.4 test", "application/pdf"))],
        headers=headers,
    )
    assert batch.status_code == 403

    delete = await client.delete(
        "/api/v1/documents/00000000-0000-0000-0000-000000000009",
        headers=headers,
    )
    assert delete.status_code == 403

    cancel = await client.patch(
        "/api/v1/jobs/00000000-0000-0000-0000-00000000000a",
        json={"action": "cancel"},
        headers=headers,
    )
    assert cancel.status_code == 403

    review = await client.patch(
        "/api/v1/records/00000000-0000-0000-0000-00000000000b/review",
        json={"decision": "approve"},
        headers=headers,
    )
    assert review.status_code == 403

    feedback = await client.post(
        "/api/v1/feedback",
        json={"record_id": "rec-viewer-1", "rating": "positive"},
        headers=headers,
    )
    assert feedback.status_code == 403

    hook = await client.post(
        "/api/v1/webhooks/test",
        json={"url": "https://example.com/hook"},
        headers=headers,
    )
    assert hook.status_code == 403

    # Reads stay open to viewer keys.
    jobs = await client.get("/api/v1/jobs", headers=headers)
    assert jobs.status_code == 200


@pytest.mark.asyncio
async def test_operator_allowed_on_document_write_routes(client: AsyncClient, db_session: AsyncSession):
    """Operator keys pass the matrix on the four named operations plus batch."""
    operator_key = "dex_operator_authz_003"
    await _seed_key(db_session, operator_key, "operator")
    headers = {"X-API-Key": operator_key}
    record_id = await _seed_review_item(db_session)

    with (
        patch("app.api.documents.detect_mime_type", return_value="application/pdf"),
        patch("app.api.documents.is_allowed_mime_type", return_value=True),
    ):
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("op.pdf", b"%PDF-1.4 test", "application/pdf")},
            headers=headers,
        )
        batch = await client.post(
            "/api/v1/documents/batch",
            files=[("files", ("op.pdf", b"%PDF-1.4 test", "application/pdf"))],
            headers=headers,
        )
    assert upload.status_code == 202
    assert batch.status_code == 202
    upload_data = upload.json()

    # Standalone document (no child rows) for the delete route.
    del_doc_id = str(uuid.uuid4())
    db_session.add(
        Document(
            id=del_doc_id,
            original_filename="del.pdf",
            stored_path=f"documents/{del_doc_id}/del.pdf",
            mime_type="application/pdf",
            file_size_bytes=10,
            sha256_hash=uuid.uuid4().hex,
        )
    )
    await db_session.commit()
    delete = await client.delete(f"/api/v1/documents/{del_doc_id}", headers=headers)
    assert delete.status_code == 204

    cancel = await client.patch(
        f"/api/v1/jobs/{upload_data['job_id']}",
        json={"action": "cancel"},
        headers=headers,
    )
    assert cancel.status_code == 200

    review = await client.patch(
        f"/api/v1/records/{record_id}/review",
        json={"decision": "approve"},
        headers=headers,
    )
    assert review.status_code == 200
