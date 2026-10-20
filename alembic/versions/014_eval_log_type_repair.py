"""Forward repair: eval_log uuid columns for databases carrying the original 012 shape.

Revision ID: 014_eval_log_type_repair
Revises: 013_record_job_unique
Create Date: 2026-09-25

The original 012 body created eval_log.id/job_id as String(36). Applied bodies
are never rewritten, so the varchar -> uuid conversion and the FK rebuild live
here for any database that ran the original shape (review P1 on PR #56).
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "014_eval_log_type_repair"
down_revision = "013_record_job_unique"
branch_labels = None
depends_on = None


def _is_legacy_string(type_: Any) -> bool:
    return isinstance(type_, sa.String)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite dev databases store uuids as text with type affinity; the
        # legacy shape is functionally identical there.
        return

    inspector = sa.inspect(bind)
    column_types = {
        col["name"]: col["type"] for col in inspector.get_columns("eval_log")
    }
    if not (
        _is_legacy_string(column_types.get("id"))
        or _is_legacy_string(column_types.get("job_id"))
    ):
        return  # already uuid-shaped (the current 012 body)

    for fk in inspector.get_foreign_keys("eval_log"):
        if fk.get("referred_table") == "extraction_jobs" and fk.get("name"):
            op.drop_constraint(fk["name"], "eval_log", type_="foreignkey")

    op.execute("ALTER TABLE eval_log ALTER COLUMN id DROP DEFAULT")
    op.execute("ALTER TABLE eval_log ALTER COLUMN id TYPE uuid USING id::uuid")
    op.execute(
        "ALTER TABLE eval_log ALTER COLUMN job_id TYPE uuid USING job_id::uuid"
    )
    op.execute(
        "ALTER TABLE eval_log ALTER COLUMN id SET DEFAULT gen_random_uuid()"
    )
    op.create_foreign_key(
        "eval_log_job_id_fkey",
        "eval_log",
        "extraction_jobs",
        ["job_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """No-op: the repaired shape is the canonical shape."""
