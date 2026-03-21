"""Add corrections table for active learning HITL corrections.

Revision ID: 009_corrections
Revises: 008_llm_traces
Create Date: 2026-03-21

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "009_corrections"
down_revision = "008_llm_traces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corrections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("record_id", sa.String, nullable=False),
        sa.Column("doc_type", sa.String(100), nullable=False),
        sa.Column("original_data", JSONB, nullable=True),
        sa.Column("corrected_data", JSONB, nullable=True),
        sa.Column("corrected_fields", JSONB, nullable=True),
        sa.Column("reviewer_id", sa.String, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_corrections_record_id", "corrections", ["record_id"])
    op.create_index("ix_corrections_doc_type", "corrections", ["doc_type"])
    op.create_index("ix_corrections_created_at", "corrections", ["created_at"])


def downgrade() -> None:
    op.drop_table("corrections")
