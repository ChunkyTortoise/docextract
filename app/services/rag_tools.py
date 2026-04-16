"""Tool definitions for agentic RAG — each tool wraps an existing service."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

class SearchResult(BaseModel):
    doc_id: str
    chunk_id: str | None = None
    content: str
    score: float
    metadata: dict = {}


# ---------------------------------------------------------------------------
# RagTools
# ---------------------------------------------------------------------------

class RagTools:
    """Five tools the agentic RAG system can call.

    All methods are async and return list[SearchResult] (or dict for metadata).
    Injecting db/client via constructor keeps everything unit-testable.
    """

    def __init__(
        self,
        db: AsyncSession | None = None,
        anthropic_client: AsyncAnthropic | None = None,
    ) -> None:
        self._db = db
        self._anthropic_client = anthropic_client

    # ------------------------------------------------------------------
    # Vector search
    # ------------------------------------------------------------------

    async def search_vectors(
        self,
        query: str,
        top_k: int = 5,
        doc_ids: list[str] | None = None,
    ) -> list[SearchResult]:
        """Semantic vector search using pgvector cosine distance."""
        if self._db is None:
            logger.warning("search_vectors called without DB session — returning empty")
            return []

        from sqlalchemy import select

        from app.models.embedding import DocumentEmbedding
        from app.models.record import ExtractedRecord
        from app.services.embedder import embed

        try:
            query_vector = await embed(query, db=self._db)
            stmt = (
                select(
                    ExtractedRecord,
                    DocumentEmbedding,
                    DocumentEmbedding.embedding.cosine_distance(query_vector).label("distance"),
                )
                .join(DocumentEmbedding, DocumentEmbedding.record_id == ExtractedRecord.id)
                .order_by("distance")
                .limit(top_k)
            )
            if doc_ids:
                import uuid as uuid_mod
                uuid_list = [uuid_mod.UUID(d) for d in doc_ids]
                stmt = stmt.where(ExtractedRecord.document_id.in_(uuid_list))

            result = await self._db.execute(stmt)
            rows = result.all()

            return [
                SearchResult(
                    doc_id=str(record.document_id),
                    chunk_id=str(embedding.id),
                    content=embedding.content_text,
                    score=round(1 - distance, 4),
                    metadata={
                        "record_id": str(record.id),
                        "document_type": record.document_type,
                        "confidence_score": record.confidence_score,
                    },
                )
                for record, embedding, distance in rows
            ]
        except Exception as exc:
            logger.warning("search_vectors failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # BM25 search
    # ------------------------------------------------------------------

    async def search_bm25(
        self,
        query: str,
        top_k: int = 5,
        doc_ids: list[str] | None = None,
    ) -> list[SearchResult]:
        """BM25 keyword search over raw text of extracted records."""
        if self._db is None:
            logger.warning("search_bm25 called without DB session — returning empty")
            return []

        from sqlalchemy import desc, select

        from app.models.record import ExtractedRecord
        from app.services.bm25 import build_index, search_bm25

        try:
            stmt = (
                select(ExtractedRecord)
                .order_by(desc(ExtractedRecord.created_at))
                .limit(10_000)
            )
            if doc_ids:
                import uuid as uuid_mod
                uuid_list = [uuid_mod.UUID(d) for d in doc_ids]
                stmt = stmt.where(ExtractedRecord.document_id.in_(uuid_list))

            result = await self._db.execute(stmt)
            records = result.scalars().all()

            if not records:
                return []

            texts = [r.raw_text or "" for r in records]
            record_ids = [str(r.id) for r in records]
            index = build_index(texts)
            hits = search_bm25(query, index, record_ids, limit=top_k)

            if not hits:
                return []

            max_score = max(s for _, s in hits) or 1.0
            id_to_record = {str(r.id): r for r in records}

            return [
                SearchResult(
                    doc_id=str(id_to_record[rid].document_id),
                    chunk_id=rid,
                    content=id_to_record[rid].raw_text or "",
                    score=round(score / max_score, 4),
                    metadata={
                        "record_id": rid,
                        "document_type": id_to_record[rid].document_type,
                        "confidence_score": id_to_record[rid].confidence_score,
                    },
                )
                for rid, score in hits
                if rid in id_to_record
            ]
        except Exception as exc:
            logger.warning("search_bm25 failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Hybrid search (vector + BM25 RRF)
    # ------------------------------------------------------------------

    async def search_hybrid(
        self,
        query: str,
        top_k: int = 5,
        alpha: float = 0.5,
    ) -> list[SearchResult]:
        """Hybrid search combining vector and BM25 via Reciprocal Rank Fusion."""
        if self._db is None:
            logger.warning("search_hybrid called without DB session — returning empty")
            return []

        try:
            vector_results = await self.search_vectors(query, top_k=top_k * 2)
            bm25_results = await self.search_bm25(query, top_k=top_k * 2)

            # Build rank maps keyed by chunk_id (falls back to doc_id)
            def _key(r: SearchResult) -> str:
                return r.chunk_id or r.doc_id

            vector_ranks: dict[str, int] = {_key(r): i for i, r in enumerate(vector_results)}
            bm25_ranks: dict[str, int] = {_key(r): i for i, r in enumerate(bm25_results)}
            all_keys = set(vector_ranks) | set(bm25_ranks)
            k = 60  # RRF constant

            scored: list[tuple[SearchResult, float]] = []
            result_map: dict[str, SearchResult] = {
                _key(r): r for r in [*vector_results, *bm25_results]
            }

            for key in all_keys:
                v_rank = vector_ranks.get(key, len(all_keys))
                b_rank = bm25_ranks.get(key, len(all_keys))
                rrf = alpha / (k + v_rank) + (1 - alpha) / (k + b_rank)
                scored.append((result_map[key], rrf))

            scored.sort(key=lambda x: x[1], reverse=True)

            return [
                SearchResult(
                    doc_id=r.doc_id,
                    chunk_id=r.chunk_id,
                    content=r.content,
                    score=round(score, 6),
                    metadata=r.metadata,
                )
                for r, score in scored[:top_k]
            ]
        except Exception as exc:
            logger.warning("search_hybrid failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Metadata lookup
    # ------------------------------------------------------------------

    async def lookup_metadata(self, doc_id: str) -> dict:
        """Retrieve document-level metadata for a given doc_id."""
        if self._db is None:
            logger.warning("lookup_metadata called without DB session")
            return {}

        import uuid as uuid_mod

        from sqlalchemy import select

        from app.models.record import ExtractedRecord

        try:
            uid = uuid_mod.UUID(doc_id)
            result = await self._db.execute(
                select(ExtractedRecord)
                .where(ExtractedRecord.document_id == uid)
                .limit(1)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return {}
            return {
                "doc_id": doc_id,
                "document_type": record.document_type,
                "confidence_score": record.confidence_score,
                "needs_review": record.needs_review,
                "validation_status": record.validation_status,
                "created_at": record.created_at.isoformat() if record.created_at else None,
            }
        except Exception as exc:
            logger.warning("lookup_metadata failed for doc_id=%s: %s", doc_id, exc)
            return {}

    # ------------------------------------------------------------------
    # Rerank via Claude
    # ------------------------------------------------------------------

    async def rerank_results(
        self,
        query: str,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """Ask Claude to re-rank results by relevance to the query.

        Falls back gracefully to the original order on any error.
        """
        if not results:
            return results

        if self._anthropic_client is None:
            logger.warning("rerank_results called without Anthropic client — returning original order")
            return results

        from app.config import settings

        snippets = "\n".join(
            f"[{i}] {r.content[:300]}" for i, r in enumerate(results)
        )
        prompt = (
            f"Given the query: \"{query}\"\n\n"
            f"Re-rank the following {len(results)} passages by relevance (most relevant first).\n"
            f"Return ONLY a JSON array of zero-based indices, e.g. [2, 0, 1].\n\n"
            f"Passages:\n{snippets}"
        )

        try:
            response = await self._anthropic_client.messages.create(
                model=settings.classification_models[0],
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()

            import json
            import re
            match = re.search(r"\[[\d,\s]+\]", raw)
            if not match:
                return results
            order = json.loads(match.group(0))
            reranked = []
            seen: set[int] = set()
            for idx in order:
                if isinstance(idx, int) and 0 <= idx < len(results) and idx not in seen:
                    reranked.append(results[idx])
                    seen.add(idx)
            # Append any results not mentioned in the rerank order
            for i, r in enumerate(results):
                if i not in seen:
                    reranked.append(r)
            return reranked
        except Exception as exc:
            logger.warning("rerank_results failed: %s", exc)
            return results
