"""Schemas for API key management endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CreateAPIKeyRequest(BaseModel):
    name: str = Field(default="default", max_length=255)
    role: str = Field(default="viewer", pattern="^(admin|operator|viewer)$")
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10000)


class CreateAPIKeyResponse(BaseModel):
    id: str
    name: str
    role: str
    api_key: str  # plaintext, returned only once
    rate_limit_per_minute: int
    created_at: datetime


class APIKeyInfo(BaseModel):
    id: str
    name: str
    role: str
    created_at: datetime
    last_used_at: datetime | None = None
    rate_limit_per_minute: int
