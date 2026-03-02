"""Add HNSW index on embeddings

Revision ID: 003
Revises: 002
Create Date: 2026-03-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_embeddings_hnsw
        ON content_embeddings USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_embeddings_hnsw;")
