"""Seed demo data for portfolio visitors.

Usage:
    python -m scripts.seed_demo
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.database import AsyncSessionLocal
from app.models.document import Document
from app.models.job import ExtractionJob
from app.models.record import ExtractedRecord

# Fixed UUIDs so the script is idempotent
DEMO_DOCS = [
    {
        "id": uuid.UUID("aaaaaaaa-0001-0000-0000-000000000001"),
        "original_filename": "invoice_INV-2026-0042.pdf",
        "stored_path": "demo/invoice_INV-2026-0042.pdf",
        "file_size_bytes": 84_210,
        "mime_type": "application/pdf",
        "sha256_hash": "demo_sha256_invoice_0042",
        "page_count": 1,
    },
    {
        "id": uuid.UUID("aaaaaaaa-0001-0000-0000-000000000002"),
        "original_filename": "receipt_homedepot.png",
        "stored_path": "demo/receipt_homedepot.png",
        "file_size_bytes": 512_000,
        "mime_type": "image/png",
        "sha256_hash": "demo_sha256_receipt_hd",
        "page_count": None,
    },
    {
        "id": uuid.UUID("aaaaaaaa-0001-0000-0000-000000000003"),
        "original_filename": "lead_form_sarah_johnson.eml",
        "stored_path": "demo/lead_form_sarah_johnson.eml",
        "file_size_bytes": 3_400,
        "mime_type": "message/rfc822",
        "sha256_hash": "demo_sha256_lead_sarah",
        "page_count": None,
    },
]

DEMO_EXTRACTED = [
    {
        "document_type": "vendor_invoice",
        "confidence_score": 0.95,
        "extracted_data": {
            "invoice_number": "INV-2026-0042",
            "vendor_name": "ABC Maintenance LLC",
            "total_amount": "1030.75",
            "currency": "USD",
            "due_date": "2026-03-31",
        },
    },
    {
        "document_type": "receipt",
        "confidence_score": 0.88,
        "extracted_data": {
            "store_name": "Home Depot #4821",
            "receipt_number": "4821-2026-88432",
            "total_amount": "25.53",
            "currency": "USD",
            "payment_method": "VISA **** 4821",
        },
    },
    {
        "document_type": "lead_capture",
        "confidence_score": 0.92,
        "extracted_data": {
            "first_name": "Sarah",
            "last_name": "Johnson",
            "email": "sarah.johnson@email.com",
            "phone": "(503) 555-0199",
            "company": "Johnson & Associates",
        },
    },
]


async def seed_demo() -> None:
    now = datetime.now(UTC)
    created = 0
    skipped = 0

    async with AsyncSessionLocal() as db:
        for i, doc_spec in enumerate(DEMO_DOCS):
            doc_id = doc_spec["id"]

            # Check existence
            existing = await db.execute(
                select(Document).where(Document.id == doc_id)
            )
            if existing.scalar_one_or_none():
                skipped += 1
                continue

            doc = Document(**doc_spec)
            db.add(doc)

            job_id = uuid.UUID(f"bbbbbbbb-0001-0000-0000-00000000000{i + 1}")
            started = now - timedelta(seconds=30 - i * 5)
            completed = now - timedelta(seconds=5 - i)
            job = ExtractionJob(
                id=job_id,
                document_id=doc_id,
                status="completed",
                progress_pct=100,
                stage_detail="Extraction complete",
                priority="standard",
                started_at=started,
                completed_at=completed,
            )
            db.add(job)

            record_id = uuid.UUID(f"cccccccc-0001-0000-0000-00000000000{i + 1}")
            rec_spec = DEMO_EXTRACTED[i]
            record = ExtractedRecord(
                id=record_id,
                job_id=job_id,
                document_id=doc_id,
                document_type=rec_spec["document_type"],
                extracted_data=rec_spec["extracted_data"],
                confidence_score=rec_spec["confidence_score"],
                needs_review=False,
                validation_status="passed",
            )
            db.add(record)
            created += 1

        await db.commit()

    print("=" * 50)
    print("  Demo Data Seed Complete")
    print("=" * 50)
    print(f"  Created: {created} document(s) + job(s) + record(s)")
    print(f"  Skipped: {skipped} (already exist)")
    print("=" * 50)


def main() -> None:
    asyncio.run(seed_demo())


if __name__ == "__main__":
    main()
