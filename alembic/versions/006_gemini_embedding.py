"""gemini_embedding_768

Revision ID: 006
Revises: 005
Create Date: 2026-03-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop HNSW index first (was created in migration 003)
    op.execute("DROP INDEX IF EXISTS content_embeddings_embedding_idx")
    # Drop old 384-dim column and add 768-dim column
    op.drop_column("content_embeddings", "embedding")
    op.add_column(
        "content_embeddings",
        sa.Column("embedding", Vector(768), nullable=True),
    )
    # Recreate HNSW index for new dimension
    op.execute(
        "CREATE INDEX content_embeddings_embedding_idx "
        "ON content_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS content_embeddings_embedding_idx")
    op.drop_column("content_embeddings", "embedding")
    op.add_column(
        "content_embeddings",
        sa.Column("embedding", Vector(384), nullable=False),
    )
    op.execute(
        "CREATE INDEX content_embeddings_embedding_idx "
        "ON content_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
