"""Export HITL corrections as fine-tuning datasets.

Supports three formats:
- supervised: OpenAI-compatible JSONL for supervised fine-tuning
- dpo: Direct Preference Optimization pairs (chosen/rejected)
- eval: Regression evaluation dataset (input/expected_output)

Each correction naturally provides a DPO pair because original_data is the
model's output (rejected) and corrected_data is the human correction (chosen).
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ExportFormat = Literal["supervised", "dpo", "eval"]
SplitType = Literal["train", "val", "all"]

_EXTRACTION_SYSTEM_PROMPT = (
    "You are a document extraction assistant. Extract structured data from the "
    "provided document text. Return a JSON object with the extracted fields."
)


class ExportStats(BaseModel):
    """Summary statistics for the fine-tuning dataset."""
    total_corrections: int
    by_doc_type: dict[str, int]
    avg_corrected_fields: float
    earliest: datetime | None
    latest: datetime | None


class FineTuneExporter:
    """Export HITL corrections as fine-tuning datasets."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def export_jsonl(
        self,
        format: ExportFormat,
        doc_type: str | None = None,
        split: SplitType = "all",
        min_field_count: int = 1,
        train_ratio: float = 0.8,
    ) -> AsyncIterator[str]:
        """Yield JSONL lines in the requested format.

        Filters: skip empty corrections, deduplicate by record_id (keep latest),
        apply optional doc_type and min_field_count filters.
        """
        corrections = await self._load_corrections(doc_type, min_field_count)

        for correction in corrections:
            if not self._passes_split(correction["record_id"], split, train_ratio):
                continue

            if format == "supervised":
                yield self._to_supervised(correction)
            elif format == "dpo":
                yield self._to_dpo(correction)
            elif format == "eval":
                yield self._to_eval(correction)

    async def get_stats(self, doc_type: str | None = None) -> ExportStats:
        """Return dataset statistics."""
        from app.models.correction import Correction

        base_query = select(Correction)
        if doc_type:
            base_query = base_query.where(Correction.doc_type == doc_type)

        # Total count
        count_result = await self._db.execute(
            select(func.count()).select_from(
                base_query.subquery()
            )
        )
        total = count_result.scalar() or 0

        # By doc_type
        type_result = await self._db.execute(
            select(Correction.doc_type, func.count())
            .group_by(Correction.doc_type)
        )
        by_doc_type = {row[0]: row[1] for row in type_result.all()}

        # Date range
        date_result = await self._db.execute(
            select(
                func.min(Correction.created_at),
                func.max(Correction.created_at),
            ).select_from(base_query.subquery())
        )
        date_row = date_result.one_or_none()
        earliest = date_row[0] if date_row else None
        latest = date_row[1] if date_row else None

        # Avg corrected fields
        all_corrections = await self._db.execute(base_query)
        rows = all_corrections.scalars().all()
        field_counts = [
            len(c.corrected_fields) for c in rows
            if c.corrected_fields
        ]
        avg_fields = sum(field_counts) / len(field_counts) if field_counts else 0.0

        return ExportStats(
            total_corrections=total,
            by_doc_type=by_doc_type,
            avg_corrected_fields=round(avg_fields, 2),
            earliest=earliest,
            latest=latest,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_corrections(
        self,
        doc_type: str | None,
        min_field_count: int,
    ) -> list[dict[str, Any]]:
        """Load corrections, deduplicate by record_id (keep latest)."""
        from app.models.correction import Correction

        query = (
            select(Correction)
            .order_by(desc(Correction.created_at))
        )
        if doc_type:
            query = query.where(Correction.doc_type == doc_type)

        result = await self._db.execute(query)
        all_rows = result.scalars().all()

        # Deduplicate: keep only the latest correction per record_id
        seen_records: set[str] = set()
        corrections: list[dict[str, Any]] = []

        for row in all_rows:
            if row.record_id in seen_records:
                continue
            seen_records.add(row.record_id)

            corrected_fields = row.corrected_fields or []
            if len(corrected_fields) < min_field_count:
                continue

            corrections.append({
                "record_id": row.record_id,
                "doc_type": row.doc_type,
                "original_data": row.original_data or {},
                "corrected_data": row.corrected_data or {},
                "corrected_fields": corrected_fields,
            })

        return corrections

    @staticmethod
    def _passes_split(record_id: str, split: SplitType, train_ratio: float) -> bool:
        """Deterministic train/val split using hash of record_id."""
        if split == "all":
            return True
        hash_val = int(hashlib.sha256(record_id.encode()).hexdigest(), 16) % 100
        is_train = hash_val < (train_ratio * 100)
        return is_train if split == "train" else not is_train

    @staticmethod
    def _to_supervised(correction: dict[str, Any]) -> str:
        """OpenAI supervised fine-tuning format."""
        row = {
            "messages": [
                {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(correction["original_data"]),
                },
                {
                    "role": "assistant",
                    "content": json.dumps(correction["corrected_data"]),
                },
            ]
        }
        return json.dumps(row, default=str)

    @staticmethod
    def _to_dpo(correction: dict[str, Any]) -> str:
        """DPO pair: corrected = chosen, original = rejected."""
        row = {
            "prompt": _EXTRACTION_SYSTEM_PROMPT,
            "chosen": json.dumps(correction["corrected_data"]),
            "rejected": json.dumps(correction["original_data"]),
            "doc_type": correction["doc_type"],
        }
        return json.dumps(row, default=str)

    @staticmethod
    def _to_eval(correction: dict[str, Any]) -> str:
        """Evaluation dataset for regression testing."""
        row = {
            "input": json.dumps(correction["original_data"]),
            "expected_output": json.dumps(correction["corrected_data"]),
            "doc_type": correction["doc_type"],
            "corrected_fields": correction["corrected_fields"],
        }
        return json.dumps(row, default=str)
