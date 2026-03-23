"""Lightweight extraction feedback endpoint.

Users can signal thumbs-up / thumbs-down on any extraction result.
Feedback aggregates by document type to surface categories that need
prompt tuning — a data flywheel feeding into the PromptRegressionTester.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db

router = APIRouter(prefix="/api/v1", tags=["feedback"])


class FeedbackRequest(BaseModel):
    record_id: str = Field(..., min_length=1)
    rating: Literal["positive", "negative"]
    comment: str | None = None
    doc_type: str | None = None


class FeedbackResponse(BaseModel):
    status: str = "recorded"
    record_id: str
    rating: str


class FeedbackSummary(BaseModel):
    total: int
    positive: int
    negative: int
    positive_rate: float
    by_doc_type: dict[str, dict[str, int]]


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    """Record user feedback on an extraction result."""
    await db.execute(
        text(
            "INSERT INTO feedback (record_id, rating, comment, doc_type) "
            "VALUES (:record_id, :rating, :comment, :doc_type)"
        ),
        {
            "record_id": request.record_id,
            "rating": request.rating,
            "comment": request.comment,
            "doc_type": request.doc_type,
        },
    )
    await db.commit()
    return FeedbackResponse(record_id=request.record_id, rating=request.rating)


@router.get("/feedback/summary", response_model=FeedbackSummary)
async def get_feedback_summary(
    db: AsyncSession = Depends(get_db),
) -> FeedbackSummary:
    """Return aggregate feedback stats."""
    rows = await db.execute(
        text(
            "SELECT rating, doc_type, COUNT(*) as cnt "
            "FROM feedback "
            "GROUP BY rating, doc_type"
        )
    )
    results = rows.fetchall()

    total = positive = negative = 0
    by_doc_type: dict[str, dict[str, int]] = {}

    for row in results:
        rating, doc_type, cnt = row.rating, row.doc_type, row.cnt
        total += cnt
        if rating == "positive":
            positive += cnt
        else:
            negative += cnt
        if doc_type:
            if doc_type not in by_doc_type:
                by_doc_type[doc_type] = {"positive": 0, "negative": 0}
            by_doc_type[doc_type][rating] = by_doc_type[doc_type].get(rating, 0) + cnt

    positive_rate = positive / total if total else 0.0
    return FeedbackSummary(
        total=total,
        positive=positive,
        negative=negative,
        positive_rate=round(positive_rate, 4),
        by_doc_type=by_doc_type,
    )
