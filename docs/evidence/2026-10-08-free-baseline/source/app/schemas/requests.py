from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UploadRequest(BaseModel):
    document_type_override: str | None = None
    priority: Literal["normal", "high", "express", "standard"] = "standard"
    webhook_url: str | None = None
    webhook_secret: str | None = None
    force: bool = False


class ReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    corrections: dict | None = None
    reviewer_notes: str | None = None


class RecordQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    document_type: str | None = None
    status: str | None = None
    needs_review: bool | None = None
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    max_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    date_from: datetime | None = None
    date_to: datetime | None = None
    search_query: str | None = None
    semantic_search: str | None = None
    sort_by: str = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"
