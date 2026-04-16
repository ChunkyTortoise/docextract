"""EvalLog model for storing LLM judge scores per extraction job."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base


class EvalLog(Base):
    __tablename__ = "eval_log"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("extraction_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    completeness: Mapped[int] = mapped_column(Integer, nullable=False)
    field_accuracy: Mapped[int] = mapped_column(Integer, nullable=False)
    hallucination_absence: Mapped[int] = mapped_column(Integer, nullable=False)
    format_compliance: Mapped[int] = mapped_column(Integer, nullable=False)
    composite: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
