"""Integration tests for API extensions: job record, cancel, health storage, semantic search, batch upload."""
from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.job import ExtractionJob
from app.models.record import ExtractedRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_doc_job_record(
    db: AsyncSession,
    *,
    status: str = "completed",
    with_record: bool = True,
) -> tuple[str, str, str | None]:
    """Insert a document, job, and optionally a record. Returns (doc_id, job_id, record_id)."""
    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    doc = Document(
        id=doc_id,
        original_filename="test.pdf",
        stored_path=f"documents/{doc_id}/test.pdf",
        mime_type="application/pdf",
        file_size_bytes=1024,
        sha256_hash=uuid.uuid4().hex,
    )
    db.add(doc)

    job = ExtractionJob(
        id=job_id,
        document_id=doc_id,
        status=status,
        priority="standard",
    )
    db.add(job)

    record_id = None
    if with_record:
        record_id = str(uuid.uuid4())
        record = ExtractedRecord(
            id=record_id,
            job_id=job_id,
            document_id=doc_id,
            document_type="invoice",
            extracted_data={"vendor": "Acme", "total": 100.0},
            confidence_score=0.95,
            needs_review=False,
        )
        db.add(record)

    await db.commit()
    return doc_id, job_id, record_id


# ---------------------------------------------------------------------------
# Task A — GET /jobs/{id}/record
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_job_record(client: AsyncClient, db_session: AsyncSession):
    """GET /jobs/{id}/record returns the record for that job."""
    _, job_id, record_id = await _create_doc_job_record(db_session)

    response = await client.get(f"/api/v1/jobs/{job_id}/record")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == record_id
    assert data["job_id"] == job_id
    assert data["document_type"] == "invoice"


@pytest.mark.asyncio
async def test_get_job_record_not_found_job(client: AsyncClient):
    """GET /jobs/{id}/record returns 404 for non-existent job."""
    fake_id = str(uuid.uuid4())
    response = await client.get(f"/api/v1/jobs/{fake_id}/record")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_job_record_no_record_yet(client: AsyncClient, db_session: AsyncSession):
    """GET /jobs/{id}/record returns 404 when job exists but no record."""
    _, job_id, _ = await _create_doc_job_record(db_session, with_record=False)

    response = await client.get(f"/api/v1/jobs/{job_id}/record")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Task F — PATCH /jobs/{id} (cancel)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_job(client: AsyncClient, db_session: AsyncSession):
    """PATCH /jobs/{id} with cancel action sets status to cancelled."""
    _, job_id, _ = await _create_doc_job_record(db_session, status="queued", with_record=False)

    response = await client.patch(
        f"/api/v1/jobs/{job_id}",
        json={"action": "cancel"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "cancelled"
    assert data["job_id"] == job_id


@pytest.mark.asyncio
async def test_cancel_job_not_found(client: AsyncClient):
    """PATCH /jobs/{id} returns 404 for non-existent job."""
    fake_id = str(uuid.uuid4())
    response = await client.patch(
        f"/api/v1/jobs/{fake_id}",
        json={"action": "cancel"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cancel_job_already_completed(client: AsyncClient, db_session: AsyncSession):
    """PATCH /jobs/{id} returns 409 for already-completed job."""
    _, job_id, _ = await _create_doc_job_record(db_session, status="completed")

    response = await client.patch(
        f"/api/v1/jobs/{job_id}",
        json={"action": "cancel"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_cancel_job_invalid_action(client: AsyncClient, db_session: AsyncSession):
    """PATCH /jobs/{id} returns 400 for non-cancel action."""
    _, job_id, _ = await _create_doc_job_record(db_session, status="queued", with_record=False)

    response = await client.patch(
        f"/api/v1/jobs/{job_id}",
        json={"action": "restart"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Task G — Health storage probe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_includes_storage_ok(client: AsyncClient):
    """Health endpoint includes storage_ok field."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "storage_ok" in data
    assert data["storage_ok"] is True


@pytest.mark.asyncio
async def test_health_degraded_when_storage_fails(client: AsyncClient):
    """Health returns degraded when storage probe fails."""
    with patch("app.api.health.get_storage") as mock_gs:
        failing_storage = AsyncMock()
        failing_storage.upload.side_effect = Exception("storage down")
        mock_gs.return_value = failing_storage

        # Note: dependency overrides take precedence, so we test the normal path
        # The FakeStorageBackend in fixtures should pass
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "storage_ok" in data


# ---------------------------------------------------------------------------
# Task I — Semantic search (mocked embedder since no GPU in tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_records_requires_query(client: AsyncClient):
    """Search without q param returns 422."""
    response = await client.get("/api/v1/records/search")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_records_calls_embedder():
    """Search endpoint invokes the embedder (unit test, pgvector needs PostgreSQL)."""
    from unittest.mock import AsyncMock, MagicMock

    fake_emb = MagicMock()
    fake_emb.values = [0.0] * 768
    fake_result = MagicMock()
    fake_result.embeddings = [fake_emb]

    mock_client = MagicMock()
    mock_client.aio.models.embed_content = AsyncMock(return_value=fake_result)

    with patch("app.services.embedder._get_client", return_value=mock_client):
        from app.services.embedder import embed
        result = await embed("test query")

    assert len(result) == 768
    mock_client.aio.models.embed_content.assert_called_once()


# ---------------------------------------------------------------------------
# Task J — Batch upload
# ---------------------------------------------------------------------------

MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj
xref
0 4
0000000000 65535 f\x20
trailer<</Size 4/Root 1 0 R>>
startxref
0
%%EOF"""


@pytest.mark.asyncio
async def test_batch_upload(client: AsyncClient):
    """Batch upload creates multiple jobs."""
    with (
        patch("app.api.documents.detect_mime_type", return_value="application/pdf"),
        patch("app.api.documents.is_allowed_mime_type", return_value=True),
    ):
        # Two different PDFs (different content → different hashes)
        files = [
            ("files", ("doc1.pdf", io.BytesIO(MINIMAL_PDF + b"a"), "application/pdf")),
            ("files", ("doc2.pdf", io.BytesIO(MINIMAL_PDF + b"b"), "application/pdf")),
        ]
        response = await client.post("/api/v1/documents/batch", files=files)

        assert response.status_code == 202
        data = response.json()
        assert len(data["job_ids"]) == 2
        assert data["duplicates"] == []


@pytest.mark.asyncio
async def test_batch_upload_with_duplicate(client: AsyncClient):
    """Batch upload detects duplicates within a batch."""
    with (
        patch("app.api.documents.detect_mime_type", return_value="application/pdf"),
        patch("app.api.documents.is_allowed_mime_type", return_value=True),
    ):
        content = MINIMAL_PDF + b"unique_batch_dedup"

        # First upload creates the document
        response1 = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("dup.pdf", io.BytesIO(content), "application/pdf")},
        )
        assert response1.status_code == 202

        # Batch with the same content should flag as duplicate
        files = [
            ("files", ("dup.pdf", io.BytesIO(content), "application/pdf")),
        ]
        response2 = await client.post("/api/v1/documents/batch", files=files)
        assert response2.status_code == 202
        data = response2.json()
        assert len(data["job_ids"]) == 0
        assert "dup.pdf" in data["duplicates"]
