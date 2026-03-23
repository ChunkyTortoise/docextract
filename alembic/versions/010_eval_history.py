"""Add eval_history table for RAGAS and LLM-judge evaluation runs.

Revision ID: 010_eval_history
Revises: 009_corrections
Create Date: 2026-03-22

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "010_eval_history"
down_revision = "009_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eval_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("fixture_name", sa.Text, nullable=False),
        sa.Column("metric_name", sa.Text, nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("threshold", sa.Float, nullable=True),
        sa.Column("reasoning", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("metadata", JSONB, nullable=True, server_default="{}"),
    )
    op.create_index(
        "idx_eval_history_metric_time",
        "eval_history",
        ["metric_name", "created_at"],
    )
    op.create_index("idx_eval_history_run", "eval_history", ["run_id"])


def downgrade() -> None:
    op.drop_index("idx_eval_history_run", table_name="eval_history")
    op.drop_index("idx_eval_history_metric_time", table_name="eval_history")
    op.drop_table("eval_history")
