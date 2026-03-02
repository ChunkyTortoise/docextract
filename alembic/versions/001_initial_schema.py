"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-01
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create set_updated_at trigger function
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # api_keys table
    op.create_table(
        "api_keys",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("key_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("rate_limit_per_minute", sa.Integer(), server_default=sa.text("60")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )

    # documents table
    op.create_table(
        "documents",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("stored_path", sa.String(1000), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "uploaded_by", UUID(as_uuid=True),
            sa.ForeignKey("api_keys.id"), nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_documents_hash", "documents", ["sha256_hash"])
    op.create_index("idx_documents_created", "documents", [sa.text("created_at DESC")])

    # extraction_jobs table
    op.create_table(
        "extraction_jobs",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "document_id", UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("status", sa.String(50), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("progress_pct", sa.Integer(), server_default=sa.text("0")),
        sa.Column("stage_detail", sa.String(500), nullable=True),
        sa.Column("priority", sa.String(20), server_default=sa.text("'standard'")),
        sa.Column("document_type_detected", sa.String(50), nullable=True),
        sa.Column("document_type_override", sa.String(50), nullable=True),
        sa.Column("extraction_pass_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("input_tokens_used", sa.Integer(), server_default=sa.text("0")),
        sa.Column("output_tokens_used", sa.Integer(), server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("attempt_number", sa.Integer(), server_default=sa.text("1")),
        sa.Column("webhook_url", sa.String(2000), nullable=True),
        sa.Column("webhook_secret_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "queued_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_jobs_status", "extraction_jobs", ["status"])
    op.create_index("idx_jobs_document", "extraction_jobs", ["document_id"])
    op.create_index("idx_jobs_created", "extraction_jobs", [sa.text("created_at DESC")])

    # extracted_records table
    op.create_table(
        "extracted_records",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "job_id", UUID(as_uuid=True),
            sa.ForeignKey("extraction_jobs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "document_id", UUID(as_uuid=True),
            sa.ForeignKey("documents.id"), nullable=False,
        ),
        sa.Column("document_type", sa.String(50), nullable=False),
        sa.Column("extracted_data", JSONB(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column(
            "validation_status", sa.String(20),
            server_default=sa.text("'pending'"),
        ),
        sa.Column("needs_review", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("corrected_data", JSONB(), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_records_type", "extracted_records", ["document_type"])
    op.create_index(
        "idx_records_review", "extracted_records", ["needs_review"],
        postgresql_where=sa.text("needs_review = true"),
    )
    op.create_index("idx_records_confidence", "extracted_records", ["confidence_score"])
    op.create_index(
        "idx_records_data", "extracted_records", ["extracted_data"],
        postgresql_using="gin",
    )

    # validation_errors table
    op.create_table(
        "validation_errors",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "record_id", UUID(as_uuid=True),
            sa.ForeignKey("extracted_records.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("field_name", sa.String(100), nullable=False),
        sa.Column("rule_name", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("expected_value", sa.Text(), nullable=True),
        sa.Column("actual_value", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_val_errors_record", "validation_errors", ["record_id"])
    op.create_index("idx_val_errors_severity", "validation_errors", ["severity"])

    # audit_logs table (BIGSERIAL)
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("actor", sa.String(255), nullable=True),
        sa.Column("old_data", JSONB(), nullable=True),
        sa.Column("new_data", JSONB(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_audit_entity", "audit_logs", ["entity_type", "entity_id"])
    op.create_index("idx_audit_created", "audit_logs", [sa.text("created_at DESC")])

    # Add updated_at triggers
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
    op.execute("DROP TRIGGER IF EXISTS trg_extracted_records_updated_at ON extracted_records;")
    op.execute("DROP TRIGGER IF EXISTS trg_extraction_jobs_updated_at ON extraction_jobs;")
    op.drop_table("audit_logs")
    op.drop_table("validation_errors")
    op.drop_table("extracted_records")
    op.drop_table("extraction_jobs")
    op.drop_table("documents")
    op.drop_table("api_keys")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")
