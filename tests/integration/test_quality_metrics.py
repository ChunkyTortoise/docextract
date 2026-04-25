"""Integration tests for GET /api/v1/metrics/quality-trend."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.eval_log import EvalLog


async def _create_eval_log(
    db: AsyncSession,
    *,
    days_ago: float = 0.5,
    completeness: int = 4,
    field_accuracy: int = 4,
    hallucination_absence: int = 5,
    format_compliance: int = 4,
    composite: float = 0.85,
) -> str:
    """Insert an EvalLog created `days_ago` days in the past."""
    log_id = str(uuid.uuid4())
    log = EvalLog(
        id=log_id,
        job_id=str(uuid.uuid4()),
        completeness=completeness,
        field_accuracy=field_accuracy,
        hallucination_absence=hallucination_absence,
        format_compliance=format_compliance,
        composite=composite,
        created_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    db.add(log)
    await db.commit()
    return log_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quality_trend_empty_db(client: AsyncClient):
    """Returns valid response shape with zeros when no eval logs exist."""
    response = await client.get("/api/v1/metrics/quality-trend")
    assert response.status_code == 200
    data = response.json()

    assert data["days"] == 30
    assert data["ewma_composite"] == []
    assert isinstance(data["per_dimension"], dict)
    for dim in ("completeness", "field_accuracy", "hallucination_absence", "format_compliance"):
        assert dim in data["per_dimension"]
        assert data["per_dimension"][dim] == []
    assert data["escalation_rate"] == 0.0
    assert data["sample_count"] == 0


@pytest.mark.asyncio
async def test_quality_trend_response_shape(client: AsyncClient, db_session: AsyncSession):
    """Returns valid response shape with eval log records present."""
    await _create_eval_log(db_session, days_ago=2)
    await _create_eval_log(db_session, days_ago=1)

    response = await client.get("/api/v1/metrics/quality-trend?days=30")
    assert response.status_code == 200
    data = response.json()

    assert data["days"] == 30
    assert data["sample_count"] >= 2
    assert len(data["ewma_composite"]) >= 1
    assert len(data["per_dimension"]) == 4

    for point in data["ewma_composite"]:
        assert "date" in point
        assert "score" in point
        assert 0.0 <= point["score"] <= 1.0

    for dim, series in data["per_dimension"].items():
        for point in series:
            assert "date" in point
            assert "score" in point
            assert 0.0 <= point["score"] <= 1.0


@pytest.mark.asyncio
async def test_quality_trend_ewma_calculation(client: AsyncClient, db_session: AsyncSession):
    """Verifies EWMA with known inputs."""
    # Day 5 ago: composite=0.8, Day 4 ago: composite=0.6
    # EWMA day1 = 0.8, day2 = 0.3*0.6 + 0.7*0.8 = 0.18 + 0.56 = 0.74
    await _create_eval_log(db_session, days_ago=5, composite=0.8)
    await _create_eval_log(db_session, days_ago=4, composite=0.6)

    response = await client.get("/api/v1/metrics/quality-trend?days=30")
    assert response.status_code == 200
    data = response.json()

    scores = [p["score"] for p in data["ewma_composite"]]
    assert len(scores) >= 2

    # The last two EWMA points should bracket the expected values
    # First point anchors at the first day's score; second decays toward 0.6
    first, *_, last = scores
    assert first == pytest.approx(0.8, abs=0.01)
    assert last == pytest.approx(0.74, abs=0.05)


@pytest.mark.asyncio
async def test_quality_trend_days_param(client: AsyncClient, db_session: AsyncSession):
    """days=1 returns only today's logs."""
    await _create_eval_log(db_session, days_ago=0.1)
    await _create_eval_log(db_session, days_ago=40)  # outside window

    response = await client.get("/api/v1/metrics/quality-trend?days=1")
    assert response.status_code == 200
    data = response.json()

    assert data["days"] == 1
    # Only the recent log should be in window
    assert data["sample_count"] >= 1


@pytest.mark.asyncio
async def test_quality_trend_auth_required(client: AsyncClient):
    """Endpoint rejects requests with missing API key."""
    response = await client.get(
        "/api/v1/metrics/quality-trend",
        headers={"X-API-Key": ""},
    )
    assert response.status_code in (401, 403)
