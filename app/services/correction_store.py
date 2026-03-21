"""Store and retrieve HITL corrections for active learning."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def store_correction(
    db: AsyncSession,
    record_id: str,
    doc_type: str,
    original_data: dict[str, Any],
    corrected_data: dict[str, Any],
    reviewer_id: str | None = None,
) -> None:
    """Store a correction in the corrections table.

    Computes field-level diff between original and corrected data.
    """
    from app.models.correction import Correction

    corrected_fields = [
        field for field in corrected_data
        if original_data.get(field) != corrected_data[field]
    ]

    correction = Correction(
        record_id=record_id,
        doc_type=doc_type,
        original_data=original_data,
        corrected_data=corrected_data,
        corrected_fields=corrected_fields,
        reviewer_id=reviewer_id,
    )
    db.add(correction)
    await db.flush()
    logger.info(
        "Stored correction for record %s (doc_type=%s, fields=%s)",
        record_id,
        doc_type,
        corrected_fields,
    )


async def get_few_shot_examples(
    db: AsyncSession,
    doc_type: str,
    limit: int = 2,
) -> list[dict[str, Any]]:
    """Retrieve recent corrections for a doc_type as few-shot examples.

    Returns list of dicts with original_data and corrected_data for
    injection into the extraction prompt.
    """
    from app.models.correction import Correction

    result = await db.execute(
        select(Correction)
        .where(Correction.doc_type == doc_type)
        .order_by(desc(Correction.created_at))
        .limit(limit)
    )
    corrections = result.scalars().all()

    return [
        {
            "original_extraction": c.original_data or {},
            "corrected_extraction": c.corrected_data or {},
            "corrected_fields": c.corrected_fields or [],
        }
        for c in corrections
    ]
