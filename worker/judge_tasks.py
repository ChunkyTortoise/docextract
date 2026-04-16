"""ARQ task: LLM-as-judge quality sampling (10% of completed jobs).

Called by process_document when hash(job_id) % 10 == 0. Loads the completed
extraction record, evaluates it across 4 quality dimensions with LLMJudge, and
writes the result to the eval_log table. Failures are logged and swallowed —
the sampling task must not affect the main job outcome.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select

from app.models.database import AsyncSessionLocal
from app.models.eval_log import EvalLog
from app.models.job import ExtractionJob
from app.models.record import ExtractedRecord
from app.services.llm_judge import LLMJudge

logger = logging.getLogger(__name__)

# Rubric descriptions for each eval_log dimension
_RUBRICS = {
    "completeness": (
        "Score whether all expected document fields are present and non-empty. "
        "A score of 1.0 means every field that should be populated is; "
        "0.0 means the extraction is nearly empty."
    ),
    "field_accuracy": (
        "Score whether the extracted field values accurately match the source "
        "document text. 1.0 means all values are exactly correct; "
        "0.0 means values are systematically wrong."
    ),
    "hallucination_absence": (
        "Score whether the extraction avoids fabricating information not present "
        "in the source. 1.0 means no hallucinations; 0.0 means many invented values."
    ),
    "format_compliance": (
        "Score whether extracted fields conform to expected data types and formats "
        "(e.g. dates as YYYY-MM-DD, amounts as floats). "
        "1.0 means full compliance; 0.0 means widespread format errors."
    ),
}


def _score_to_int(score: float) -> int:
    """Map a 0.0–1.0 judge score to a 1–5 integer dimension rating."""
    return max(1, min(5, round(score * 4) + 1))


async def judge_extraction_sample(ctx: dict[str, Any], job_id: str) -> None:
    """Evaluate extraction quality for one sampled job and write to eval_log.

    Called by ARQ — returns None on success or swallowed failure.
    """
    try:
        async with AsyncSessionLocal() as db:
            job_result = await db.execute(
                select(ExtractionJob).where(ExtractionJob.id == job_id)
            )
            job = job_result.scalar_one_or_none()
            if not job:
                logger.warning("judge_extraction_sample: job %s not found", job_id)
                return

            record_result = await db.execute(
                select(ExtractedRecord).where(ExtractedRecord.job_id == job_id)
            )
            record = record_result.scalar_one_or_none()
            if not record:
                logger.warning("judge_extraction_sample: no record for job %s", job_id)
                return

            source_text = record.raw_text or ""
            answer = json.dumps(record.extracted_data or {}, default=str)
            doc_type = record.document_type or "unknown"

            judge = LLMJudge()
            dimension_scores: dict[str, int] = {}

            for dim, rubric in _RUBRICS.items():
                judge_result = await judge.evaluate(
                    question=f"Evaluate {dim} of {doc_type} extraction",
                    answer=answer,
                    contexts=[source_text[:2000]],
                    rubric=rubric,
                )
                # Default to neutral (3) when judge is disabled or call fails
                dimension_scores[dim] = _score_to_int(judge_result.score) if judge_result else 3

            composite = sum(dimension_scores.values()) / (5.0 * len(dimension_scores))

            db.add(EvalLog(
                job_id=job_id,
                completeness=dimension_scores["completeness"],
                field_accuracy=dimension_scores["field_accuracy"],
                hallucination_absence=dimension_scores["hallucination_absence"],
                format_compliance=dimension_scores["format_compliance"],
                composite=round(composite, 4),
            ))
            await db.commit()
            logger.info(
                "judge_extraction_sample: scored job %s composite=%.3f", job_id, composite
            )

    except Exception as exc:
        # Sampling must not break the main job pipeline
        logger.warning("judge_extraction_sample failed for job %s: %s", job_id, exc)
