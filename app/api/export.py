"""Streaming CSV/JSON export endpoint."""
from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import get_api_key
from app.dependencies import get_db
from app.models.api_key import APIKey
from app.models.record import ExtractedRecord

router = APIRouter(prefix="/records", tags=["export"])


@router.get("/export")
async def export_records(
    format: str = Query("csv", pattern="^(csv|json)$"),
    document_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
):
    """Stream all records as CSV or JSON (no memory buffering)."""
    query = select(ExtractedRecord).order_by(desc(ExtractedRecord.created_at))
    if document_type:
        query = query.where(ExtractedRecord.document_type == document_type)

    result = await db.execute(query)
    records = result.scalars().all()

    if format == "csv":

        def csv_generator():
            fieldnames = [
                "id",
                "document_type",
                "confidence_score",
                "needs_review",
                "validation_status",
                "created_at",
            ]
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            yield output.getvalue()

            for record in records:
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writerow(
                    {
                        "id": str(record.id),
                        "document_type": record.document_type,
                        "confidence_score": record.confidence_score,
                        "needs_review": record.needs_review,
                        "validation_status": record.validation_status or "",
                        "created_at": str(record.created_at),
                    }
                )
                yield output.getvalue()

        return StreamingResponse(
            csv_generator(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=records.csv"},
        )

    else:  # JSON

        def json_generator():
            yield "["
            for i, record in enumerate(records):
                if i > 0:
                    yield ","
                yield json.dumps(
                    {
                        "id": str(record.id),
                        "document_type": record.document_type,
                        "extracted_data": record.extracted_data,
                        "confidence_score": record.confidence_score,
                        "needs_review": record.needs_review,
                        "created_at": str(record.created_at),
                    }
                )
            yield "]"

        return StreamingResponse(
            json_generator(),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=records.json"},
        )
