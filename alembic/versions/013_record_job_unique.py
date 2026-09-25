"""Unique record-per-job constraint: redelivery creates one logical record.

Revision ID: 013_record_job_unique
Revises: 012_eval_log
Create Date: 2026-09-25

"""
from __future__ import annotations

from alembic import op

revision = "013_record_job_unique"
down_revision = "012_eval_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_extracted_records_job_id",
        "extracted_records",
        ["job_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_extracted_records_job_id", table_name="extracted_records")
