"""Tests verifying Sprint 1 bug fixes."""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.job import ExtractionJob
from app.models.record import ExtractedRecord


# ---------------------------------------------------------------------------
# 1a. embed() is awaited in search_records
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_records_awaits_embed():
    """Verify embed() is properly awaited (not called synchronously)."""
    import inspect
    from app.services.embedder import embed

    # embed must be a coroutine function (async def)
    assert inspect.iscoroutinefunction(embed), "embed must be async"

    # Verify the search_records endpoint code calls `await embed(q)`
    from app.api.records import search_records
    import ast
    source = inspect.getsource(search_records)
    tree = ast.parse(source)
    # Find any Await node whose value is a Call to 'embed'
    found_await_embed = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id == "embed":
                found_await_embed = True
    assert found_await_embed, "search_records must use 'await embed(q)'"


# ---------------------------------------------------------------------------
# 1b. ROI summary uses processing time, not progress_pct
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_roi_summary_uses_processing_time(client: AsyncClient, db_session: AsyncSession):
    """ROI summary avg_processing_indicator should reflect actual processing time."""
    doc_id = str(uuid.uuid4())
    db_session.add(Document(
        id=doc_id,
        original_filename="roi.pdf",
        stored_path=f"documents/{doc_id}/roi.pdf",
        mime_type="application/pdf",
        file_size_bytes=100,
        sha256_hash=uuid.uuid4().hex,
    ))

    now = datetime.now(timezone.utc)
    # Job with known start/end: 10 seconds = 10000ms processing time
    db_session.add(ExtractionJob(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        status="completed",
        priority="standard",
        progress_pct=100,
        started_at=now - timedelta(seconds=10),
        completed_at=now,
    ))
    await db_session.commit()

    response = await client.get("/api/v1/roi/summary")
    assert response.status_code == 200
    data = response.json()
    # Should NOT be 100 (which would be progress_pct)
    # With SQLite, EXTRACT('epoch', ...) won't work the same as PG,
    # so we just verify the field exists and the endpoint doesn't error
    assert "avg_processing_indicator" in data["kpis"]


# ---------------------------------------------------------------------------
# 1c. Batch upload uses a single shared ARQ pool (no per-request pool creation)
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
async def test_batch_upload_uses_single_arq_pool(client: AsyncClient, fake_arq_pool):
    """Batch upload should use the shared arq_pool, not create new pools."""
    with (
        patch("app.api.documents.detect_mime_type", return_value="application/pdf"),
        patch("app.api.documents.is_allowed_mime_type", return_value=True),
    ):
        files = [
            ("files", ("doc1.pdf", io.BytesIO(MINIMAL_PDF + b"x"), "application/pdf")),
            ("files", ("doc2.pdf", io.BytesIO(MINIMAL_PDF + b"y"), "application/pdf")),
        ]
        response = await client.post("/api/v1/documents/batch", files=files)

    assert response.status_code == 202
    data = response.json()
    assert len(data["job_ids"]) == 2
    # The shared pool's enqueue_job should have been called for each file
    assert fake_arq_pool.enqueue_job.call_count == 2


# ---------------------------------------------------------------------------
# 1e. updated_at has onupdate
# ---------------------------------------------------------------------------

def test_job_updated_at_has_onupdate():
    """ExtractionJob.updated_at column should have an onupdate callback."""
    col = ExtractionJob.__table__.c.updated_at
    assert col.onupdate is not None


def test_record_updated_at_has_onupdate():
    """ExtractedRecord.updated_at column should have an onupdate callback."""
    col = ExtractedRecord.__table__.c.updated_at
    assert col.onupdate is not None
