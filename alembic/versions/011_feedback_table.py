"""Add feedback table for lightweight thumbs-up/down extraction quality signals.

Revision ID: 011_feedback
Revises: 010_eval_history
Create Date: 2026-03-22

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "011_feedback"
down_revision = "010_eval_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("record_id", sa.String, nullable=False),
        sa.Column("rating", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("doc_type", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_feedback_record_id", "feedback", ["record_id"])
    op.create_index("ix_feedback_doc_type", "feedback", ["doc_type"])
    op.create_index("ix_feedback_created_at", "feedback", ["created_at"])


def downgrade() -> None:
    op.drop_table("feedback")
