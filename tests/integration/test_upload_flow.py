"""Integration tests for document upload flow."""
from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from httpx import AsyncClient

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
async def test_upload_document(client: AsyncClient):
    """Upload creates document and job, returns 202."""
    with (
        patch("app.api.documents.detect_mime_type", return_value="application/pdf"),
        patch("app.api.documents.is_allowed_mime_type", return_value=True),
    ):
        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
        )

        assert response.status_code == 202
        data = response.json()
        assert "document_id" in data
        assert "job_id" in data
        assert data["filename"] == "test.pdf"
        assert data["duplicate"] is False


@pytest.mark.asyncio
async def test_upload_duplicate_detection(client: AsyncClient):
    """Re-uploading the same file returns duplicate=True."""
    with (
        patch("app.api.documents.detect_mime_type", return_value="application/pdf"),
        patch("app.api.documents.is_allowed_mime_type", return_value=True),
    ):
        # First upload
        response1 = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
        )
        assert response1.status_code == 202

        # Second upload (same content)
        response2 = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
        )
        assert response2.status_code == 202
        data = response2.json()
        assert data["duplicate"] is True


@pytest.mark.asyncio
async def test_upload_unsupported_type(client: AsyncClient):
    """Uploading unsupported file type returns 415."""
    with (
        patch("app.api.documents.detect_mime_type", return_value="application/zip"),
        patch("app.api.documents.is_allowed_mime_type", return_value=False),
    ):
        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.zip", io.BytesIO(b"PK\x03\x04"), "application/zip")},
        )
        assert response.status_code == 415


@pytest.mark.asyncio
async def test_upload_oversized_file(client: AsyncClient):
    """Uploading file over size limit returns 400."""
    with patch("app.config.settings.max_file_size_mb", 0):  # 0 MB limit
        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("big.pdf", io.BytesIO(b"x" * 100), "application/pdf")},
        )
        assert response.status_code == 400
