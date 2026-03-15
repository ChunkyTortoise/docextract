from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base


class ExecutiveReport(Base):
    __tablename__ = "executive_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    date_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    format: Mapped[str] = mapped_column(String(20), nullable=False, default="both")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="generated")
    files_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_executive_reports_generated_at", "generated_at"),
    )
