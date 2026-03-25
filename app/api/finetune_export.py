"""Fine-tuning data export endpoints.

Export HITL corrections as training datasets in supervised JSONL, DPO pair,
or evaluation formats. Supports doc_type filtering and deterministic
train/val splitting.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import get_api_key
from app.dependencies import get_db
from app.models.api_key import APIKey
from app.services.finetune_exporter import ExportFormat, ExportStats, FineTuneExporter, SplitType

router = APIRouter(tags=["finetune"])


@router.get("/finetune/export")
async def export_finetune_data(
    format: ExportFormat = Query("supervised", description="Export format: supervised, dpo, or eval"),
    doc_type: str | None = Query(None, description="Filter by document type"),
    split: SplitType = Query("all", description="Dataset split: train, val, or all"),
    min_field_count: int = Query(1, ge=1, description="Min corrected fields to include"),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
) -> StreamingResponse:
    """Export corrections as JSONL for fine-tuning.

    Streams newline-delimited JSON. Each line is a training example in the
    requested format. Deduplicates by record_id (keeps latest correction).
    """
    exporter = FineTuneExporter(db)

    async def generate():
        async for line in exporter.export_jsonl(
            format=format,
            doc_type=doc_type,
            split=split,
            min_field_count=min_field_count,
        ):
            yield line + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f"attachment; filename=finetune_{format}_{split}.jsonl"},
    )


@router.get("/finetune/stats", response_model=ExportStats)
async def finetune_stats(
    doc_type: str | None = Query(None, description="Filter by document type"),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
) -> ExportStats:
    """Return dataset statistics: counts, date range, avg corrected fields."""
    exporter = FineTuneExporter(db)
    return await exporter.get_stats(doc_type=doc_type)
