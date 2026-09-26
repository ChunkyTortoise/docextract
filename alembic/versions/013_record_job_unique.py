"""Unique record-per-job constraint: redelivery creates one logical record.

Revision ID: 013_record_job_unique
Revises: 012_eval_log
Create Date: 2026-09-25

"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "013_record_job_unique"
down_revision = "012_eval_log"
branch_labels = None
depends_on = None

# Deterministic reconciliation for pre-existing redelivery duplicates: keep
# the earliest record per job (created_at, id), matching the idempotency
# guard's first-writer-wins semantics. Runs before the unique constraint so a
# database that predates the guard upgrades without failing on old dupes.
DEDUPE_KEEP_FIRST_SQL = """
DELETE FROM extracted_records
WHERE id NOT IN (
    SELECT keep_id FROM (
        SELECT id AS keep_id,
               ROW_NUMBER() OVER (
                   PARTITION BY job_id
                   ORDER BY created_at ASC, id ASC
               ) AS rn
        FROM extracted_records
    ) ranked
    WHERE rn = 1
)
"""


def upgrade() -> None:
    op.execute(sa.text(DEDUPE_KEEP_FIRST_SQL))
    op.create_index(
        "uq_extracted_records_job_id",
        "extracted_records",
        ["job_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_extracted_records_job_id", table_name="extracted_records")
