"""Correction model for storing HITL correction history."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    record_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    original_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    corrected_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    corrected_fields: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    reviewer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )
