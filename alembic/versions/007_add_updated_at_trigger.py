"""add updated_at trigger for extraction_jobs and extracted_records

Revision ID: 007
Revises: 006
Create Date: 2026-03-15
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create trigger function for updating updated_at on row modification
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_extraction_jobs_updated_at
        BEFORE UPDATE ON extraction_jobs
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    op.execute("""
        CREATE TRIGGER trg_extracted_records_updated_at
        BEFORE UPDATE ON extracted_records
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_extracted_records_updated_at ON extracted_records")
    op.execute("DROP TRIGGER IF EXISTS trg_extraction_jobs_updated_at ON extraction_jobs")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
