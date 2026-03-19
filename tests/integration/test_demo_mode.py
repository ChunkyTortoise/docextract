"""Demo mode tests: page serving and read-only key enforcement."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_demo_page_returns_html(demo_client: AsyncClient):
    response = await demo_client.get("/demo")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert b"DocExtract AI" in response.content


@pytest.mark.asyncio
async def test_demo_key_allows_get_records(demo_client: AsyncClient):
    response = await demo_client.get("/api/v1/records")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_demo_key_blocks_post_upload(demo_client: AsyncClient):
    response = await demo_client.post(
        "/api/v1/documents/upload",
        files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_demo_key_blocks_delete(demo_client: AsyncClient):
    response = await demo_client.delete("/api/v1/documents/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_demo_key_blocks_review_claim(demo_client: AsyncClient):
    response = await demo_client.post(
        "/api/v1/review/items/00000000-0000-0000-0000-000000000001/claim"
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_demo_key_allows_get_stats(demo_client: AsyncClient):
    response = await demo_client.get("/api/v1/stats")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_demo_key_allows_get_roi_summary(demo_client: AsyncClient):
    response = await demo_client.get("/api/v1/roi/summary")
    assert response.status_code == 200
    assert "kpis" in response.json()
