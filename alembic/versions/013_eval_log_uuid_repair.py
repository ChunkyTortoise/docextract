"""Repair legacy eval_log UUID columns and its exact job foreign key.

Revision ID: 013_eval_log_uuid_repair
Revises: 012_eval_log

Fresh installs use the corrected 012 body. This forward revision preserves valid
legacy score rows, rejects invalid casts/orphans/collisions, and restores a
missing or incorrectly configured job FK without touching unrelated constraints.
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "013_eval_log_uuid_repair"
down_revision = "012_eval_log"
branch_labels = None
depends_on = None


def _is_job_fk(fk: dict[str, Any]) -> bool:
    return (
        fk.get("constrained_columns") == ["job_id"]
        and fk.get("referred_table") == "extraction_jobs"
        and fk.get("referred_columns") == ["id"]
        and fk.get("referred_schema") in (None, "public")
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite's existing text affinity is unchanged.

    inspector = sa.inspect(bind)
    columns = {column["name"]: column["type"] for column in inspector.get_columns("eval_log")}
    legacy_id = isinstance(columns["id"], sa.String)
    legacy_job_id = isinstance(columns["job_id"], sa.String)
    foreign_keys = inspector.get_foreign_keys("eval_log")
    job_keys = [fk for fk in foreign_keys if "job_id" in fk.get("constrained_columns", [])]
    if any(not _is_job_fk(fk) for fk in job_keys):
        raise RuntimeError("Unexpected eval_log.job_id foreign key; inspect before repair")
    if len(job_keys) > 1:
        raise RuntimeError("Multiple eval_log.job_id foreign keys; inspect before repair")
    correct_fk = bool(job_keys) and job_keys[0].get("options", {}).get("ondelete", "").upper() == "SET NULL"
    if not legacy_id and not legacy_job_id and correct_fk:
        return

    replace_fk = legacy_job_id or not correct_fk
    if replace_fk:
        for fk in job_keys:
            op.drop_constraint(fk["name"], "eval_log", type_="foreignkey")
    if legacy_id:
        op.execute("ALTER TABLE eval_log ALTER COLUMN id DROP DEFAULT")
        op.execute("ALTER TABLE eval_log ALTER COLUMN id TYPE uuid USING id::uuid")
        op.execute("ALTER TABLE eval_log ALTER COLUMN id SET DEFAULT gen_random_uuid()")
    if legacy_job_id:
        op.execute("ALTER TABLE eval_log ALTER COLUMN job_id TYPE uuid USING job_id::uuid")
    if replace_fk:
        op.create_foreign_key(
            "eval_log_job_id_fkey", "eval_log", "extraction_jobs", ["job_id"], ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Forward-only repair: downgrading does not recreate the broken VARCHAR shape."""
