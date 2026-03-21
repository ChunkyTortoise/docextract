"""LLM call trace model for observability."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, Float, Index, Integer, String, Text
)

from app.models.database import Base


class LLMTrace(Base):
    __tablename__ = "llm_traces"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trace_id = Column(String(36), nullable=True, index=True)
    request_id = Column(String(36), nullable=True, index=True)
    model = Column(String(100), nullable=False)
    operation = Column(String(50), nullable=False)  # extract/classify/correct/embed
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=True)
    retries = Column(Integer, nullable=False, default=0)
    prompt_hash = Column(String(16), nullable=True)
    status = Column(String(20), nullable=False, default="success")  # success/error/timeout
    error_message = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_llm_traces_model", "model"),
        Index("ix_llm_traces_operation", "operation"),
        Index("ix_llm_traces_created_at", "created_at"),
        Index("ix_llm_traces_status", "status"),
    )
