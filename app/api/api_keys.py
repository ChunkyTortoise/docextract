"""Self-service API key management endpoints."""
from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import require_roles
from app.dependencies import get_db
from app.models.api_key import APIKey
from app.schemas.api_keys import APIKeyInfo, CreateAPIKeyRequest, CreateAPIKeyResponse
from app.utils.hashing import hash_api_key

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post("", response_model=CreateAPIKeyResponse, status_code=201)
async def create_api_key(
    body: CreateAPIKeyRequest | None = None,
    db: AsyncSession = Depends(get_db),
    caller: APIKey = Depends(require_roles("admin")),
) -> CreateAPIKeyResponse:
    """Generate a new API key. Plaintext is returned only once."""
    if body is None:
        body = CreateAPIKeyRequest()

    raw_key = f"dex_{secrets.token_hex(32)}"
    key_hash = hash_api_key(raw_key)
    key_id = str(uuid.uuid4())

    new_key = APIKey(
        id=key_id,
        name=body.name,
        role=body.role,
        key_hash=key_hash,
        is_active=True,
        rate_limit_per_minute=body.rate_limit_per_minute,
    )
    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)

    return CreateAPIKeyResponse(
        id=key_id,
        name=new_key.name,
        role=new_key.role,
        api_key=raw_key,
        rate_limit_per_minute=new_key.rate_limit_per_minute,
        created_at=new_key.created_at,
    )


@router.get("", response_model=list[APIKeyInfo])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    caller: APIKey = Depends(require_roles("admin")),
) -> list[APIKeyInfo]:
    """List all active API keys. No plaintext keys returned."""
    result = await db.execute(
        select(APIKey).where(APIKey.is_active == True)  # noqa: E712
    )
    keys = result.scalars().all()
    return [
        APIKeyInfo(
            id=str(k.id),
            name=k.name,
            role=k.role,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
            rate_limit_per_minute=k.rate_limit_per_minute,
        )
        for k in keys
    ]


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    caller: APIKey = Depends(require_roles("admin")),
) -> Response:
    """Revoke an API key by setting is_active=False."""
    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.is_active == True)  # noqa: E712
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    key.is_active = False
    await db.commit()
    return Response(status_code=204)
