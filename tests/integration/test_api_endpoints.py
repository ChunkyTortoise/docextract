"""Integration tests for all API endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    """Health check returns 200."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "db_ok" in data
    assert "redis_ok" in data


@pytest.mark.asyncio
async def test_health_no_auth_required(client: AsyncClient):
    """Health check works without API key."""
    # Override header to remove API key
    response = await client.get(
        "/api/v1/health", headers={"X-API-Key": ""}
    )
    # Health endpoint has no auth dependency, so it should still work
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_jobs_auth_required(client: AsyncClient):
    """Jobs endpoint rejects invalid API key."""
    response = await client.get(
        "/api/v1/jobs", headers={"X-API-Key": "invalid-key"}
    )
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_list_jobs_empty(client: AsyncClient):
    """Jobs list returns empty on fresh DB."""
    response = await client.get("/api/v1/jobs")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_nonexistent_job(client: AsyncClient):
    """Returns 404 for non-existent job."""
    response = await client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_records_empty(client: AsyncClient):
    """Records list returns empty pagination."""
    response = await client.get("/api/v1/records")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_stats_endpoint(client: AsyncClient):
    """Stats returns aggregate counts."""
    response = await client.get("/api/v1/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_documents" in data
    assert "success_rate" in data
    assert "needs_review" in data
    assert "jobs_last_24h" in data


@pytest.mark.asyncio
async def test_export_csv_empty(client: AsyncClient):
    """Export CSV works on empty DB."""
    response = await client.get("/api/v1/records/export?format=csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_export_json_empty(client: AsyncClient):
    """Export JSON works on empty DB."""
    response = await client.get("/api/v1/records/export?format=json")
    assert response.status_code == 200
    body = response.json()
    assert body == []


@pytest.mark.asyncio
async def test_get_nonexistent_record(client: AsyncClient):
    """Returns 404 for non-existent record."""
    response = await client.get("/api/v1/records/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_request_id_header(client: AsyncClient):
    """Every response should have X-Request-ID header."""
    response = await client.get("/api/v1/health")
    assert "x-request-id" in response.headers


@pytest.mark.asyncio
async def test_jobs_pagination(client: AsyncClient):
    """Jobs endpoint respects page and page_size params."""
    response = await client.get("/api/v1/jobs?page=1&page_size=5")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_records_filter_by_confidence(client: AsyncClient):
    """Records endpoint accepts min_confidence filter."""
    response = await client.get("/api/v1/records?min_confidence=0.9")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_feedback_post_auth_required(client: AsyncClient):
    """Feedback POST rejects missing API key."""
    response = await client.post(
        "/api/v1/feedback",
        json={"record_id": "rec-123", "rating": "positive"},
        headers={"X-API-Key": ""},
    )
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_feedback_summary_auth_required(client: AsyncClient):
    """Feedback summary GET rejects missing API key."""
    response = await client.get(
        "/api/v1/feedback/summary",
        headers={"X-API-Key": ""},
    )
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_agent_eval_auth_required(client: AsyncClient):
    """Agent eval POST rejects missing API key."""
    response = await client.post(
        "/api/v1/agent-eval",
        json={"question": "test"},
        headers={"X-API-Key": ""},
    )
    assert response.status_code in (401, 403)
