"""Extracted records endpoints."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import get_api_key
from app.config import settings
from app.dependencies import get_db
from app.models.api_key import APIKey
from app.models.embedding import DocumentEmbedding
from app.models.record import ExtractedRecord
from app.schemas.requests import ReviewRequest
from app.schemas.responses import PaginatedRecords, record_item_from_db
from app.services.pii_sanitizer import redact_pii

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

    items = [record_item_from_db(r) for r in records]

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
    mode: str = Query("vector", pattern="^(vector|bm25|hybrid|graph)$"),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
):
    """Semantic search over extracted records using embeddings.

    mode=vector: pure pgvector cosine distance (default)
    mode=bm25: pure BM25 text match
    mode=hybrid: RRF combination of vector + BM25 rankings (+ graph when enabled)
    mode=graph: graph + BM25 retrieval over persisted knowledge graph
    """
    from app.services.bm25 import build_index, search_bm25
    from app.services.embedder import embed

    if mode == "graph":
        if not settings.graph_retrieval_enabled:
            raise HTTPException(
                400,
                "Graph retrieval is disabled. Set GRAPH_RETRIEVAL_ENABLED=true to use mode=graph.",
            )
        from app.services.graph_rag.store import search_graph

        hits = search_graph(q, k=limit)
        if not hits:
            return []

        best_by_record: dict[str, float] = {}
        for hit in hits:
            rid = hit.doc_id
            if rid not in best_by_record or hit.score > best_by_record[rid]:
                best_by_record[rid] = hit.score

        sorted_ids = sorted(
            best_by_record, key=lambda r: best_by_record[r], reverse=True
        )[:limit]
        result = await db.execute(
            select(ExtractedRecord).where(ExtractedRecord.id.in_(sorted_ids))
        )
        id_to_record = {str(r.id): r for r in result.scalars().all()}
        return [
            {
                "record": record_item_from_db(id_to_record[rid]),
                "similarity": round(best_by_record[rid], 4),
            }
            for rid in sorted_ids
            if rid in id_to_record
        ]

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
                "record": record_item_from_db(id_to_record[rid]),
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
                "record": record_item_from_db(record),
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
    vector_ranks = {str(record.id): i for i, (record, _) in enumerate(rows)}

    if settings.graph_retrieval_enabled:
        from app.services.graph_rag.rrf import reciprocal_rank_fusion
        from app.services.graph_rag.store import search_graph

        graph_hits = search_graph(q, k=limit * 2)
        graph_ranks: dict[str, int] = {}
        for rank, hit in enumerate(graph_hits):
            if hit.doc_id not in graph_ranks:
                graph_ranks[hit.doc_id] = rank

        fused = reciprocal_rank_fusion(
            [vector_ranks, bm25_ranks, graph_ranks],
            k=60,
            default_rank=len(record_ids),
        )
        id_to_row = {str(record.id): (record, distance) for record, distance in rows}
        scored_ids = sorted(fused, key=lambda rid: fused[rid], reverse=True)[:limit]
        return [
            {
                "record": record_item_from_db(id_to_row[rid][0]),
                "similarity": round(1 - id_to_row[rid][1], 4),
            }
            for rid in scored_ids
            if rid in id_to_row
        ]

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
            "record": record_item_from_db(record),
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
    if settings.pii_redaction_enabled:
        # Build a redacted copy; never mutate the ORM row or the response
        # would get flushed back to the database.
        return {
            "id": str(record.id),
            "job_id": str(record.job_id),
            "document_id": str(record.document_id),
            "document_type": record.document_type,
            "extracted_data": redact_pii(record.extracted_data),
            "raw_text": redact_pii(record.raw_text),
            "confidence_score": record.confidence_score,
            "validation_status": record.validation_status,
            "needs_review": record.needs_review,
            "review_reason": record.review_reason,
            "reviewed_by": record.reviewed_by,
            "reviewed_at": record.reviewed_at,
            "corrected_data": redact_pii(record.corrected_data),
            "reviewer_notes": redact_pii(record.reviewer_notes),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
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

    # Map API decision to the validation_status CHECK-constraint domain;
    # storing the raw decision ("approve") violates the constraint.
    record.validation_status = "approved" if review.decision == "approve" else "failed"
    record.reviewed_at = datetime.now(UTC)
    record.reviewed_by = str(api_key.id)
    record.needs_review = False

    if review.corrections:
        record.corrected_data = (
            redact_pii(review.corrections)
            if settings.pii_redaction_enabled
            else review.corrections
        )
    if review.reviewer_notes:
        record.reviewer_notes = (
            redact_pii(review.reviewer_notes)
            if settings.pii_redaction_enabled
            else review.reviewer_notes
        )

    await db.commit()
    return {"status": "ok", "record_id": record_id, "decision": review.decision}


@router.get("/{record_id}/guardrails")
async def run_record_guardrails(
    record_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
):
    """Run guardrails (PII detection + hallucination grounding) on a record on demand."""
    from app.services.guardrails import run_guardrails

    result = await db.execute(
        select(ExtractedRecord).where(ExtractedRecord.id == record_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(404, "Record not found")

    guardrail_result = run_guardrails(
        record.extracted_data,
        source_text=record.raw_text or "",
    )

    return {
        "record_id": record_id,
        "passed": guardrail_result.passed,
        "pii_detected": [
            {"type": m.pattern_type, "field": m.field_path, "redacted": m.redacted}
            for m in guardrail_result.pii_detected
        ],
        "grounding": [
            {"field": g.field, "status": g.status, "reason": g.reason}
            for g in guardrail_result.grounding
        ],
    }
