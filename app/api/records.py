"""Extracted records endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import get_api_key
from app.dependencies import get_db
from app.models.api_key import APIKey
from app.models.embedding import DocumentEmbedding
from app.models.record import ExtractedRecord
from app.schemas.requests import ReviewRequest
from app.schemas.responses import PaginatedRecords, RecordItem

router = APIRouter(prefix="/records", tags=["records"])


@router.get("", response_model=PaginatedRecords)
async def list_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=100),
    document_type: str | None = Query(None),
    needs_review: bool | None = Query(None),
    min_confidence: float | None = Query(None, ge=0, le=1),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
) -> PaginatedRecords:
    """List extracted records with filters."""
    conditions = []
    if document_type:
        conditions.append(ExtractedRecord.document_type == document_type)
    if needs_review is not None:
        conditions.append(ExtractedRecord.needs_review == needs_review)
    if min_confidence is not None:
        conditions.append(ExtractedRecord.confidence_score >= min_confidence)

    query = select(ExtractedRecord)
    if conditions:
        query = query.where(and_(*conditions))

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar() or 0

    query = (
        query.order_by(desc(ExtractedRecord.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    records = result.scalars().all()

    items = [
        RecordItem(
            id=str(r.id),
            job_id=str(r.job_id),
            document_id=str(r.document_id),
            document_type=r.document_type,
            extracted_data=r.extracted_data,
            confidence_score=r.confidence_score,
            needs_review=r.needs_review,
            validation_status=r.validation_status,
            review_status=None,
            created_at=r.created_at,
        )
        for r in records
    ]

    return PaginatedRecords(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_next=(page * page_size) < total,
    )


@router.get("/search")
async def search_records(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=100),
    mode: str = Query("vector", pattern="^(vector|bm25|hybrid)$"),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
):
    """Semantic search over extracted records using embeddings.

    mode=vector: pure pgvector cosine distance (default)
    mode=bm25: pure BM25 text match
    mode=hybrid: RRF combination of vector + BM25 rankings
    """
    from app.services.embedder import embed
    from app.services.bm25 import build_index, search_bm25

    if mode == "bm25":
        # Pure BM25: load all record texts, build index, search
        all_result = await db.execute(
            select(ExtractedRecord).order_by(desc(ExtractedRecord.created_at)).limit(10000)
        )
        all_records = all_result.scalars().all()
        if not all_records:
            return []

        texts = [r.raw_text or "" for r in all_records]
        record_ids = [str(r.id) for r in all_records]
        index = build_index(texts)
        bm25_hits = search_bm25(q, index, record_ids, limit=limit)

        id_to_record = {str(r.id): r for r in all_records}
        return [
            {
                "record": RecordItem(
                    id=str(id_to_record[rid].id),
                    job_id=str(id_to_record[rid].job_id),
                    document_id=str(id_to_record[rid].document_id),
                    document_type=id_to_record[rid].document_type,
                    extracted_data=id_to_record[rid].extracted_data,
                    confidence_score=id_to_record[rid].confidence_score,
                    needs_review=id_to_record[rid].needs_review,
                    validation_status=id_to_record[rid].validation_status,
                    review_status=None,
                    created_at=id_to_record[rid].created_at,
                ),
                "similarity": round(score / max(s for _, s in bm25_hits), 4) if bm25_hits else 0,
            }
            for rid, score in bm25_hits
            if rid in id_to_record
        ]

    # Vector search (used for both vector and hybrid modes)
    query_vector = await embed(q)
    stmt = (
        select(
            ExtractedRecord,
            DocumentEmbedding.embedding.cosine_distance(query_vector).label("distance"),
        )
        .join(DocumentEmbedding, DocumentEmbedding.record_id == ExtractedRecord.id)
        .order_by("distance")
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()

    if mode == "vector" or not rows:
        return [
            {
                "record": RecordItem(
                    id=str(record.id),
                    job_id=str(record.job_id),
                    document_id=str(record.document_id),
                    document_type=record.document_type,
                    extracted_data=record.extracted_data,
                    confidence_score=record.confidence_score,
                    needs_review=record.needs_review,
                    validation_status=record.validation_status,
                    review_status=None,
                    created_at=record.created_at,
                ),
                "similarity": round(1 - distance, 4),
            }
            for record, distance in rows
        ]

    # Hybrid: RRF combination
    vector_records = [r for r, _ in rows]
    texts = [r.raw_text or "" for r in vector_records]
    record_ids = [str(r.id) for r in vector_records]
    index = build_index(texts)
    bm25_hits = search_bm25(q, index, record_ids, limit=limit)
    bm25_ranks = {rid: rank for rank, (rid, _) in enumerate(bm25_hits)}

    def rrf_score(vector_rank: int, rid: str) -> float:
        bm25_rank = bm25_ranks.get(rid, len(record_ids))
        return 1 / (60 + bm25_rank) + 1 / (60 + vector_rank)

    scored = [
        (record, distance, rrf_score(i, str(record.id)))
        for i, (record, distance) in enumerate(rows)
    ]
    scored.sort(key=lambda x: x[2], reverse=True)

    return [
        {
            "record": RecordItem(
                id=str(record.id),
                job_id=str(record.job_id),
                document_id=str(record.document_id),
                document_type=record.document_type,
                extracted_data=record.extracted_data,
                confidence_score=record.confidence_score,
                needs_review=record.needs_review,
                validation_status=record.validation_status,
                review_status=None,
                created_at=record.created_at,
            ),
            "similarity": round(1 - distance, 4),
        }
        for record, distance, _ in scored[:limit]
    ]


@router.get("/{record_id}")
async def get_record(
    record_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
):
    """Get a single extracted record with full data."""
    result = await db.execute(
        select(ExtractedRecord).where(ExtractedRecord.id == record_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(404, "Record not found")
    return record


@router.patch("/{record_id}/review", status_code=200)
async def review_record(
    record_id: str,
    review: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
):
    """Submit human review decision for a record."""
    result = await db.execute(
        select(ExtractedRecord).where(ExtractedRecord.id == record_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(404, "Record not found")

    record.validation_status = review.decision
    record.reviewed_at = datetime.now(timezone.utc)
    record.reviewed_by = str(api_key.id)
    record.needs_review = False

    if review.corrections:
        record.corrected_data = review.corrections
    if review.reviewer_notes:
        record.reviewer_notes = review.reviewer_notes

    await db.commit()
    return {"status": "ok", "record_id": record_id, "decision": review.decision}
