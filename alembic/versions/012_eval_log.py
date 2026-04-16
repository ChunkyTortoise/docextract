"""Add eval_log table for storing LLM judge scores per extraction job.

Revision ID: 012_eval_log
Revises: 011_feedback
Create Date: 2026-04-06

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "012_eval_log"
down_revision = "011_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eval_log",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("completeness", sa.Integer, nullable=False),
        sa.Column("field_accuracy", sa.Integer, nullable=False),
        sa.Column("hallucination_absence", sa.Integer, nullable=False),
        sa.Column("format_compliance", sa.Integer, nullable=False),
        sa.Column("composite", sa.Float, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["extraction_jobs.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_eval_log_job_id", "eval_log", ["job_id"])
    op.create_index("ix_eval_log_created_at", "eval_log", ["created_at"])


def downgrade() -> None:
    op.drop_table("eval_log")
