"""Integration tests for API key management endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_api_key(client: AsyncClient):
    """POST /api-keys creates a key and returns plaintext once."""
    response = await client.post(
        "/api/v1/api-keys",
        json={"name": "my-test-key", "rate_limit_per_minute": 100},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "my-test-key"
    assert data["rate_limit_per_minute"] == 100
    assert data["api_key"].startswith("dex_")
    assert len(data["api_key"]) == 4 + 64  # "dex_" + 32 bytes hex
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_create_api_key_defaults(client: AsyncClient):
    """POST /api-keys with empty body uses defaults."""
    response = await client.post("/api/v1/api-keys", json={})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "default"
    assert data["rate_limit_per_minute"] == 60


@pytest.mark.asyncio
async def test_list_api_keys_empty_start(client: AsyncClient):
    """GET /api-keys returns at least the seeded test key."""
    response = await client.get("/api/v1/api-keys")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1  # at least the test key from conftest
    # No plaintext keys in response
    for key_info in data:
        assert "api_key" not in key_info
        assert "key_hash" not in key_info
        assert "id" in key_info
        assert "name" in key_info
        assert "rate_limit_per_minute" in key_info


@pytest.mark.asyncio
async def test_list_api_keys_after_create(client: AsyncClient):
    """GET /api-keys includes newly created key."""
    create_resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "list-check-key"},
    )
    assert create_resp.status_code == 201
    created_id = create_resp.json()["id"]

    list_resp = await client.get("/api/v1/api-keys")
    assert list_resp.status_code == 200
    ids = [k["id"] for k in list_resp.json()]
    assert created_id in ids


@pytest.mark.asyncio
async def test_delete_api_key(client: AsyncClient):
    """DELETE /api-keys/{id} revokes the key."""
    create_resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "to-delete"},
    )
    assert create_resp.status_code == 201
    key_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/api-keys/{key_id}")
    assert delete_resp.status_code == 204

    # Key should no longer appear in listing
    list_resp = await client.get("/api/v1/api-keys")
    ids = [k["id"] for k in list_resp.json()]
    assert key_id not in ids


@pytest.mark.asyncio
async def test_delete_api_key_not_found(client: AsyncClient):
    """DELETE /api-keys/{id} returns 404 for non-existent key."""
    response = await client.delete(
        "/api/v1/api-keys/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_api_key_already_revoked(client: AsyncClient):
    """DELETE on already-revoked key returns 404."""
    create_resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "double-delete"},
    )
    key_id = create_resp.json()["id"]

    await client.delete(f"/api/v1/api-keys/{key_id}")
    second_delete = await client.delete(f"/api/v1/api-keys/{key_id}")
    assert second_delete.status_code == 404


@pytest.mark.asyncio
async def test_api_keys_auth_required(client: AsyncClient):
    """All api-keys endpoints reject invalid auth."""
    bad_headers = {"X-API-Key": "invalid-key-999"}

    post_resp = await client.post(
        "/api/v1/api-keys", json={}, headers=bad_headers
    )
    assert post_resp.status_code in (401, 403)

    get_resp = await client.get("/api/v1/api-keys", headers=bad_headers)
    assert get_resp.status_code in (401, 403)

    del_resp = await client.delete(
        "/api/v1/api-keys/some-id", headers=bad_headers
    )
    assert del_resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_created_key_is_usable(client: AsyncClient):
    """A newly created key can authenticate requests."""
    create_resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "usable-key", "rate_limit_per_minute": 1000},
    )
    new_key = create_resp.json()["api_key"]

    # Use the new key to list keys
    list_resp = await client.get(
        "/api/v1/api-keys", headers={"X-API-Key": new_key}
    )
    assert list_resp.status_code == 200
