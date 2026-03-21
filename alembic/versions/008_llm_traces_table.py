"""Add llm_traces table for LLM observability.

Revision ID: 008_llm_traces
Revises: 007
Create Date: 2026-03-20

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "008_llm_traces"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_traces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trace_id", sa.String(36), nullable=True),
        sa.Column("request_id", sa.String(36), nullable=True),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("operation", sa.String(50), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("retries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("prompt_hash", sa.String(16), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="success"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_llm_traces_model", "llm_traces", ["model"])
    op.create_index("ix_llm_traces_operation", "llm_traces", ["operation"])
    op.create_index("ix_llm_traces_created_at", "llm_traces", ["created_at"])
    op.create_index("ix_llm_traces_status", "llm_traces", ["status"])
    op.create_index("ix_llm_traces_trace_id", "llm_traces", ["trace_id"])
    op.create_index("ix_llm_traces_request_id", "llm_traces", ["request_id"])


def downgrade() -> None:
    op.drop_table("llm_traces")
