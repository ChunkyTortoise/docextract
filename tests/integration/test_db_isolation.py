"""Regression: rows committed by a route must not leak into later tests.

The two tests below run in file order. The first commits rows through a real
route (the client fixture also commits its seeded API key). The second never
touches the client, so on an isolated database it must see no rows at all.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import APIKey

_committed: dict[str, str] = {}


@pytest.mark.asyncio
async def test_route_commit_writes_row(client: AsyncClient, db_session: AsyncSession):
    response = await client.post("/api/v1/api-keys", json={"name": "isolation-probe"})
    assert response.status_code == 201
    key_id = response.json()["id"]

    # The route committed, so the row is durable for the rest of this test.
    await db_session.rollback()
    assert await db_session.get(APIKey, key_id) is not None
    _committed["key_id"] = key_id


@pytest.mark.asyncio
async def test_later_test_sees_clean_database(db_session: AsyncSession):
    if "key_id" not in _committed:
        pytest.skip("depends on test_route_commit_writes_row running first")

    assert await db_session.get(APIKey, _committed["key_id"]) is None
    count = await db_session.scalar(select(func.count()).select_from(APIKey))
    assert count == 0
