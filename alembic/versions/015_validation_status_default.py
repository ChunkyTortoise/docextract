"""Fix extracted_records.validation_status default to a domain-valid value.

Revision ID: 015_validation_status_default
Revises: 014_eval_log_type_repair
Create Date: 2026-09-25

Migration 001 set the server default to 'pending', but migration 005's
ck_extracted_records_validation_status_domain excludes that value, so any raw
insert relying on the default violated the check. The default becomes
'pending_review', matching the ORM default and the domain. The domain itself
is unchanged and no rows can carry 'pending' (005 validates on add).
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "015_validation_status_default"
down_revision = "014_eval_log_type_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite dev databases take validation_status from the ORM's Python
        # default; migrations beyond 005 are a PostgreSQL path.
        return

    op.alter_column(
        "extracted_records",
        "validation_status",
        existing_type=sa.String(20),
        server_default=sa.text("'pending_review'"),
    )


def downgrade() -> None:
    """No-op: the corrected default is the canonical state."""
