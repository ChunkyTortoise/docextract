from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="queued"
    )
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    stage_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default="standard")
    document_type_detected: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    document_type_override: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    extraction_pass_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    webhook_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    webhook_secret_encrypted: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    __table_args__ = (
        Index("idx_jobs_status", "status"),
        Index("idx_jobs_document", "document_id"),
        Index("idx_jobs_created", "created_at", postgresql_using="btree"),
    )
