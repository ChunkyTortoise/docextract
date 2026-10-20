"""Webhook destination, secret handling, and dedup behavior on the upload path."""
from __future__ import annotations

import io
import socket
from unittest.mock import patch

import pytest
from httpx import AsyncClient

MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
xref
0 2
trailer<</Size 2/Root 1 0 R>>
startxref
0
%%EOF"""


async def _post_upload(
    client: AsyncClient,
    *,
    form: dict | None = None,
    content: bytes = MINIMAL_PDF,
    params: dict | None = None,
):
    with (
        patch("app.api.documents.detect_mime_type", return_value="application/pdf"),
        patch("app.api.documents.is_allowed_mime_type", return_value=True),
    ):
        return await client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.pdf", io.BytesIO(content), "application/pdf")},
            data=form or {},
            params=params or {},
        )


@pytest.mark.asyncio
async def test_upload_rejects_http_webhook(client: AsyncClient):
    resp = await _post_upload(client, form={"webhook_url": "http://example.com/hook"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_private_webhook_target(client: AsyncClient):
    resp = await _post_upload(client, form={"webhook_url": "https://127.0.0.1/hook"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_webhook_hostname_resolving_private(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 0))],
    )
    resp = await _post_upload(client, form={"webhook_url": "https://internal.example.com/hook"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_webhook_secret_without_aes_key(client: AsyncClient):
    resp = await _post_upload(client, form={"webhook_secret": "shh"})
    assert resp.status_code == 400
    assert "AES_KEY" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_force_duplicates_do_not_break_later_uploads(client: AsyncClient):
    first = await _post_upload(client, params={"force": "true"})
    assert first.status_code == 202
    second = await _post_upload(client, params={"force": "true"})
    assert second.status_code == 202
    third = await _post_upload(client)
    assert third.status_code == 202
    assert third.json()["duplicate"] is True
