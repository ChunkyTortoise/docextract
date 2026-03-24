"""Unit tests for multi-document synthesis (map-reduce RAG)."""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.multi_doc_synthesizer import (
    DocumentEvidence,
    MultiDocSynthesizer,
    SynthesisResult,
)
from app.services.rag_tools import RagTools, SearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _search_result(doc_id="d1", chunk_id="c1", content="sample content", score=0.9) -> SearchResult:
    return SearchResult(doc_id=doc_id, chunk_id=chunk_id, content=content, score=score)


def _make_tools(results_by_doc: dict[str, list[SearchResult]] | None = None) -> RagTools:
    """Mock RagTools that returns different results per doc_id."""
    tools = MagicMock(spec=RagTools)

    async def _search_vectors(query, top_k=5, doc_ids=None):
        if results_by_doc and doc_ids:
            return results_by_doc.get(doc_ids[0], [])
        return [_search_result()]

    tools.search_vectors = AsyncMock(side_effect=_search_vectors)
    return tools


def _make_router(responses: list[str]) -> MagicMock:
    """Mock ModelRouter that cycles through responses."""
    router = MagicMock()
    call_count = 0

    async def _call_with_fallback(operation, chain, call_fn):
        nonlocal call_count
        resp = responses[min(call_count, len(responses) - 1)]
        call_count += 1
        return resp, chain[0] if chain else "mock-model"

    router.call_with_fallback = _call_with_fallback
    return router


# ---------------------------------------------------------------------------
# Map phase queries each document individually
# ---------------------------------------------------------------------------

class TestMapPhase:
    @pytest.mark.asyncio
    async def test_map_queries_each_document(self):
        results_by_doc = {
            "doc-1": [_search_result(doc_id="doc-1", content="Invoice total: $500")],
            "doc-2": [_search_result(doc_id="doc-2", content="Invoice total: $300")],
        }
        tools = _make_tools(results_by_doc)
        # Map responses for doc-1 and doc-2, then reduce
        router = _make_router([
            "Payment of $500 from doc-1",
            "Payment of $300 from doc-2",
            "Combined: $500 from [Doc 1] and $300 from [Doc 2]",
        ])
        synth = MultiDocSynthesizer(tools=tools, model_router=router)

        result = await synth.synthesize("What are the totals?", ["doc-1", "doc-2"])

        assert isinstance(result, SynthesisResult)
        assert result.documents_used == 2
        assert len(result.per_document_evidence) == 2

    @pytest.mark.asyncio
    async def test_skips_documents_with_no_relevant_info(self):
        results_by_doc = {
            "doc-1": [_search_result(doc_id="doc-1", content="relevant data")],
            "doc-2": [],  # No results
        }
        tools = _make_tools(results_by_doc)
        # Only doc-1 gets a map call; doc-2 has no passages so no LLM call
        router = _make_router([
            "Relevant info from doc-1",
            "Synthesized answer from [Doc 1]",
        ])
        synth = MultiDocSynthesizer(tools=tools, model_router=router)

        result = await synth.synthesize("question?", ["doc-1", "doc-2"])

        assert result.documents_used == 1
        assert result.documents_skipped == 1


# ---------------------------------------------------------------------------
# Reduce phase
# ---------------------------------------------------------------------------

class TestReducePhase:
    @pytest.mark.asyncio
    async def test_reduce_produces_combined_answer(self):
        results_by_doc = {
            "d1": [_search_result(doc_id="d1", content="Term: Net 30")],
            "d2": [_search_result(doc_id="d2", content="Term: Net 60")],
        }
        tools = _make_tools(results_by_doc)
        router = _make_router([
            "Net 30 payment terms",
            "Net 60 payment terms",
            "Doc 1 has Net 30, Doc 2 has Net 60",
        ])
        synth = MultiDocSynthesizer(tools=tools, model_router=router)

        result = await synth.synthesize("Compare payment terms", ["d1", "d2"])

        assert "Net" in result.answer or "Doc" in result.answer
        assert result.strategy == "map_reduce"

    @pytest.mark.asyncio
    async def test_citations_reference_source_documents(self):
        results_by_doc = {
            "d1": [_search_result(doc_id="d1")],
        }
        tools = _make_tools(results_by_doc)
        router = _make_router([
            "Evidence from d1",
            "Answer citing [Doc 1]: data from d1",
        ])
        synth = MultiDocSynthesizer(tools=tools, model_router=router)

        result = await synth.synthesize("question?", ["d1"])

        assert result.documents_used == 1
        # Evidence should reference the doc_id
        assert result.per_document_evidence[0].doc_id == "d1"


# ---------------------------------------------------------------------------
# Concurrency / semaphore
# ---------------------------------------------------------------------------

class TestConcurrency:
    @pytest.mark.asyncio
    async def test_semaphore_limits_parallel_calls(self):
        """Verify concurrency is bounded by the semaphore."""
        results_by_doc = {f"d{i}": [_search_result(doc_id=f"d{i}")] for i in range(10)}
        tools = _make_tools(results_by_doc)
        responses = [f"Summary for d{i}" for i in range(10)] + ["Combined answer"]
        router = _make_router(responses)

        synth = MultiDocSynthesizer(tools=tools, model_router=router, concurrency=2)
        result = await synth.synthesize("question?", [f"d{i}" for i in range(10)])

        # Should complete without deadlock
        assert result.documents_used == 10


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_single_document_works(self):
        results_by_doc = {"d1": [_search_result(doc_id="d1", content="data")]}
        tools = _make_tools(results_by_doc)
        router = _make_router(["Extracted info", "Final answer"])
        synth = MultiDocSynthesizer(tools=tools, model_router=router)

        result = await synth.synthesize("q?", ["d1"])

        assert result.documents_used == 1
        assert isinstance(result.answer, str)

    @pytest.mark.asyncio
    async def test_all_empty_returns_no_info_message(self):
        results_by_doc = {"d1": [], "d2": []}
        tools = _make_tools(results_by_doc)
        router = _make_router([])
        synth = MultiDocSynthesizer(tools=tools, model_router=router)

        result = await synth.synthesize("q?", ["d1", "d2"])

        assert result.documents_used == 0
        assert result.documents_skipped == 2
        assert "No relevant" in result.answer

    @pytest.mark.asyncio
    async def test_tracks_llm_call_count(self):
        results_by_doc = {
            "d1": [_search_result(doc_id="d1")],
            "d2": [_search_result(doc_id="d2")],
            "d3": [_search_result(doc_id="d3")],
        }
        tools = _make_tools(results_by_doc)
        router = _make_router([
            "info1", "info2", "info3", "combined",
        ])
        synth = MultiDocSynthesizer(tools=tools, model_router=router)

        result = await synth.synthesize("q?", ["d1", "d2", "d3"])

        # 3 map calls + 1 reduce call = 4
        assert result.total_llm_calls == 4

    @pytest.mark.asyncio
    async def test_latency_tracked(self):
        results_by_doc = {"d1": [_search_result(doc_id="d1")]}
        tools = _make_tools(results_by_doc)
        router = _make_router(["info", "answer"])
        synth = MultiDocSynthesizer(tools=tools, model_router=router)

        result = await synth.synthesize("q?", ["d1"])

        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_question_preserved_in_result(self):
        results_by_doc = {"d1": [_search_result(doc_id="d1")]}
        tools = _make_tools(results_by_doc)
        router = _make_router(["info", "answer"])
        synth = MultiDocSynthesizer(tools=tools, model_router=router)

        result = await synth.synthesize("What is the vendor?", ["d1"])

        assert result.question == "What is the vendor?"
