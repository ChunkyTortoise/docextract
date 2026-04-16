"""Multi-document synthesis via map-reduce RAG.

Given a question and a set of document IDs, retrieves relevant excerpts from
each document (map phase), then synthesizes a combined answer with per-document
citations (reduce phase). Demonstrates concurrent LLM orchestration patterns.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from pydantic import BaseModel

from app.services.rag_tools import RagTools

if TYPE_CHECKING:
    from app.services.model_router import ModelRouter

logger = logging.getLogger(__name__)

_MAP_SYSTEM = (
    "You are a document analysis assistant. Given a document excerpt, "
    "extract the specific information relevant to the question. "
    "If no relevant info exists, respond with exactly: NONE"
)

_REDUCE_SYSTEM = (
    "You are a synthesis assistant. Given information from multiple documents, "
    "synthesize a comprehensive answer. Cite which document each fact comes from "
    "using [Doc N] references. Be concise and factual."
)


class DocumentEvidence(BaseModel):
    """Per-document evidence extracted during the map phase."""
    doc_id: str
    summary: str
    relevance_score: float
    passages_found: int


class SynthesisResult(BaseModel):
    """Result of multi-document synthesis."""
    answer: str
    per_document_evidence: list[DocumentEvidence]
    documents_used: int
    documents_skipped: int
    total_llm_calls: int
    latency_ms: float
    strategy: str = "map_reduce"
    question: str


class MultiDocSynthesizer:
    """Map-reduce synthesis across multiple documents."""

    def __init__(
        self,
        tools: RagTools,
        model_router: ModelRouter,
        concurrency: int = 3,
    ) -> None:
        self._tools = tools
        self._router = model_router
        self._semaphore = asyncio.Semaphore(concurrency)

    async def synthesize(
        self,
        question: str,
        doc_ids: list[str],
    ) -> SynthesisResult:
        """Run map-reduce synthesis across the given documents."""
        start = time.monotonic()
        llm_calls = 0

        # ── Map phase: extract evidence from each document concurrently ──
        async def _map_one(doc_id: str) -> DocumentEvidence:
            async with self._semaphore:
                results = await self._tools.search_vectors(
                    query=question, top_k=3, doc_ids=[doc_id],
                )
                if not results:
                    return DocumentEvidence(
                        doc_id=doc_id, summary="NONE",
                        relevance_score=0.0, passages_found=0,
                    )

                context = "\n\n".join(
                    f"[{i + 1}] {r.content[:500]}" for i, r in enumerate(results)
                )
                prompt = (
                    f"Question: {question}\n\n"
                    f"Document excerpts:\n{context}\n\n"
                    "Extract the specific information relevant to the question."
                )
                summary = await self._call_llm(
                    system=_MAP_SYSTEM, user=prompt, operation="synthesis_map",
                )
                avg_score = sum(r.score for r in results) / len(results) if results else 0.0

                return DocumentEvidence(
                    doc_id=doc_id,
                    summary=summary,
                    relevance_score=round(avg_score, 4),
                    passages_found=len(results),
                )

        map_results = await asyncio.gather(
            *[_map_one(doc_id) for doc_id in doc_ids]
        )
        llm_calls += len(doc_ids)

        # Filter out documents with no relevant info
        relevant = [e for e in map_results if e.summary.strip().upper() != "NONE"]
        skipped = len(map_results) - len(relevant)

        if not relevant:
            elapsed = (time.monotonic() - start) * 1000
            return SynthesisResult(
                answer="No relevant information found across the provided documents.",
                per_document_evidence=list(map_results),
                documents_used=0,
                documents_skipped=len(doc_ids),
                total_llm_calls=llm_calls,
                latency_ms=round(elapsed, 1),
                question=question,
            )

        # ── Reduce phase: synthesize combined answer ─────────────────────
        evidence_block = "\n\n".join(
            f"[Doc {i + 1} — {e.doc_id}]:\n{e.summary}"
            for i, e in enumerate(relevant)
        )
        reduce_prompt = (
            f"Question: {question}\n\n"
            f"Information from {len(relevant)} documents:\n{evidence_block}\n\n"
            "Synthesize a comprehensive answer citing [Doc N] for each fact."
        )
        answer = await self._call_llm(
            system=_REDUCE_SYSTEM, user=reduce_prompt, operation="synthesis_reduce",
        )
        llm_calls += 1

        elapsed = (time.monotonic() - start) * 1000
        return SynthesisResult(
            answer=answer,
            per_document_evidence=list(map_results),
            documents_used=len(relevant),
            documents_skipped=skipped,
            total_llm_calls=llm_calls,
            latency_ms=round(elapsed, 1),
            question=question,
        )

    async def _call_llm(self, system: str, user: str, operation: str) -> str:
        """Route an LLM call through ModelRouter."""
        from anthropic import AsyncAnthropic

        from app.config import settings

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)

        async def _call(model: str) -> str:
            response = await client.messages.create(
                model=model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return response.content[0].text

        try:
            result, _ = await self._router.call_with_fallback(
                operation=operation,
                chain=settings.extraction_models,
                call_fn=_call,
            )
            return result
        except Exception as exc:
            logger.warning("LLM call failed for %s: %s", operation, exc)
            return ""
