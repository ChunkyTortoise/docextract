from __future__ import annotations

import uuid

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
