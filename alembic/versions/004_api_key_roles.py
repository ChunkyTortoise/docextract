"""Add role to api_keys

Revision ID: 004
Revises: 003
Create Date: 2026-03-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("role", sa.String(length=32), nullable=False, server_default=sa.text("'admin'")),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "role")
