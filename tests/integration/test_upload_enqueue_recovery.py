"""Upload-path fault injection: a failed queue submit leaves recoverable work.

Lane B B5 acceptance: fault injection before/after commit and enqueue leaves
recoverable work — nothing is half-recorded and nothing is silently dropped.
"""
from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from httpx import AsyncClient

MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
xref
0 2
trailer<</Size 2/Root 1 0 R>>endobj
startxref
0
%%EOF"""


def _unique_pdf(tag: str) -> bytes:
    """Per-test bytes: the upload dedup is global across the shared test session."""
    return MINIMAL_PDF + f"% {tag}".encode()


async def _post_upload(client: AsyncClient, content: bytes = MINIMAL_PDF):
    with (
        patch("app.api.documents.detect_mime_type", return_value="application/pdf"),
        patch("app.api.documents.is_allowed_mime_type", return_value=True),
    ):
        return await client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.pdf", io.BytesIO(content), "application/pdf")},
        )


@pytest.mark.asyncio
async def test_upload_enqueue_failure_leaves_recoverable_job(
    client: AsyncClient, fake_arq_pool, db_session
):
    from app.models.job import ExtractionJob

    fake_arq_pool.enqueue_job.side_effect = RuntimeError("redis down")

    resp = await _post_upload(client, content=_unique_pdf("single"))

    assert resp.status_code == 202
    body = resp.json()
    assert "recovery" in body["message"]

    result = await db_session.execute(
        ExtractionJob.__table__.select().where(
            ExtractionJob.__table__.c.id == body["job_id"]
        )
    )
    row = result.first()
    assert row is not None, "committed job must survive a failed enqueue"
    assert row.status == "queued"
    assert "deferred to recovery" in (row.error_message or "")


@pytest.mark.asyncio
async def test_batch_enqueue_failure_reports_deferred_jobs(
    client: AsyncClient, fake_arq_pool, db_session
):
    from app.models.job import ExtractionJob

    fake_arq_pool.enqueue_job.side_effect = RuntimeError("redis down")

    with (
        patch("app.api.documents.detect_mime_type", return_value="application/pdf"),
        patch("app.api.documents.is_allowed_mime_type", return_value=True),
    ):
        resp = await client.post(
            "/api/v1/documents/batch",
            files=[
                ("files", ("a.pdf", io.BytesIO(_unique_pdf("batch-a")), "application/pdf")),
                # Distinct bytes: identical content would hit the soft dedup.
                ("files", ("b.pdf", io.BytesIO(_unique_pdf("batch-b")), "application/pdf")),
            ],
        )

    assert resp.status_code == 202
    body = resp.json()
    assert len(body["job_ids"]) == 2
    assert sorted(body["deferred"]) == sorted(body["job_ids"])
    assert all(e["reason"] == "enqueue_deferred_to_recovery" for e in body["errors"])

    # Both jobs are committed rows — the recovery cron can pick them up.
    for job_id in body["job_ids"]:
        result = await db_session.execute(
            ExtractionJob.__table__.select().where(
                ExtractionJob.__table__.c.id == job_id
            )
        )
        assert result.first() is not None
