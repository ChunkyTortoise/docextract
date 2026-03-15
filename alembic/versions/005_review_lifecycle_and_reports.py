"""Review lifecycle hardening and executive report metadata.

Revision ID: 005
Revises: 004
Create Date: 2026-03-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_extracted_records_validation_status_domain",
        "extracted_records",
        "validation_status IN ('pending_review','claimed','approved','corrected','passed','failed')",
    )
    op.create_index(
        "idx_records_status_review_created",
        "extracted_records",
        ["validation_status", "needs_review", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_records_reviewer_reviewed_at",
        "extracted_records",
        ["reviewed_by", "reviewed_at"],
        unique=False,
    )

    op.create_table(
        "executive_reports",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("date_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("format", sa.String(length=20), nullable=False, server_default=sa.text("'both'")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'generated'")),
        sa.Column("files_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("summary_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_executive_reports_generated_at",
        "executive_reports",
        ["generated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_executive_reports_generated_at", table_name="executive_reports")
    op.drop_table("executive_reports")

    op.drop_index("idx_records_reviewer_reviewed_at", table_name="extracted_records")
    op.drop_index("idx_records_status_review_created", table_name="extracted_records")
    op.drop_constraint(
        "ck_extracted_records_validation_status_domain",
        "extracted_records",
        type_="check",
    )
