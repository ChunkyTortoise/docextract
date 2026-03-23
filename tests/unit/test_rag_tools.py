"""Unit tests for RagTools — each tool returns list[SearchResult] or dict."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.rag_tools import RagTools, SearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    doc_id="doc-1",
    record_id="rec-1",
    raw_text="invoice from Acme total 500",
    doc_type="invoice",
    confidence=0.9,
) -> MagicMock:
    r = MagicMock()
    r.id = record_id
    r.document_id = doc_id
    r.raw_text = raw_text
    r.document_type = doc_type
    r.confidence_score = confidence
    r.created_at = None
    r.needs_review = False
    r.validation_status = "passed"
    return r


def _make_embedding(record_id="rec-1", text="invoice from Acme total 500") -> MagicMock:
    e = MagicMock()
    e.id = "emb-1"
    e.record_id = record_id
    e.content_text = text
    return e


# ---------------------------------------------------------------------------
# search_vectors
# ---------------------------------------------------------------------------

class TestSearchVectors:
    @pytest.mark.asyncio
    async def test_returns_list_of_search_results(self):
        db = AsyncMock()
        record = _make_record()
        embedding = _make_embedding()
        distance = 0.2

        db.execute = AsyncMock(return_value=MagicMock(
            all=MagicMock(return_value=[(record, embedding, distance)])
        ))

        with patch("app.services.embedder.embed", new_callable=AsyncMock, return_value=[0.1] * 768):
            tools = RagTools(db=db)
            results = await tools.search_vectors("invoice total")

        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].content == "invoice from Acme total 500"
        assert results[0].score == pytest.approx(0.8, abs=0.01)

    @pytest.mark.asyncio
    async def test_no_db_returns_empty(self):
        tools = RagTools(db=None)
        results = await tools.search_vectors("query")
        assert results == []

    @pytest.mark.asyncio
    async def test_doc_ids_filter_passed_through(self):
        """When doc_ids is provided, the query should include a WHERE clause — we verify
        the stmt is executed (no crash) and the result is still list[SearchResult]."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        with patch("app.services.embedder.embed", new_callable=AsyncMock, return_value=[0.0] * 768):
            tools = RagTools(db=db)
            results = await tools.search_vectors("invoice", doc_ids=["00000000-0000-0000-0000-000000000001"])

        assert isinstance(results, list)
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_db_results_returns_empty_list(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        with patch("app.services.embedder.embed", new_callable=AsyncMock, return_value=[0.0] * 768):
            tools = RagTools(db=db)
            results = await tools.search_vectors("nothing here")

        assert results == []


# ---------------------------------------------------------------------------
# search_bm25
# ---------------------------------------------------------------------------

class TestSearchBm25:
    @pytest.mark.asyncio
    async def test_returns_list_of_search_results(self):
        db = AsyncMock()
        record = _make_record()
        db.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[record])))
        ))

        tools = RagTools(db=db)
        results = await tools.search_bm25("invoice")

        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, SearchResult)

    @pytest.mark.asyncio
    async def test_no_db_returns_empty(self):
        tools = RagTools(db=None)
        results = await tools.search_bm25("query")
        assert results == []

    @pytest.mark.asyncio
    async def test_doc_ids_filter_forwarded(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        ))

        tools = RagTools(db=db)
        results = await tools.search_bm25("invoice", doc_ids=["00000000-0000-0000-0000-000000000001"])

        assert isinstance(results, list)
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_corpus_returns_empty(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        ))

        tools = RagTools(db=db)
        results = await tools.search_bm25("anything")
        assert results == []


# ---------------------------------------------------------------------------
# search_hybrid
# ---------------------------------------------------------------------------

class TestSearchHybrid:
    @pytest.mark.asyncio
    async def test_returns_list_of_search_results(self):
        """Hybrid merges vector + bm25 results."""
        db = AsyncMock()
        tools = RagTools(db=db)

        mock_results = [
            SearchResult(doc_id="d1", chunk_id="c1", content="text one", score=0.9),
            SearchResult(doc_id="d2", chunk_id="c2", content="text two", score=0.7),
        ]

        tools.search_vectors = AsyncMock(return_value=mock_results)
        tools.search_bm25 = AsyncMock(return_value=mock_results[:1])

        results = await tools.search_hybrid("query", top_k=5)

        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, SearchResult)

    @pytest.mark.asyncio
    async def test_no_db_returns_empty(self):
        tools = RagTools(db=None)
        results = await tools.search_hybrid("query")
        assert results == []


# ---------------------------------------------------------------------------
# rerank_results
# ---------------------------------------------------------------------------

class TestRerankResults:
    @pytest.mark.asyncio
    async def test_returns_reranked_list(self):
        results = [
            SearchResult(doc_id="d1", chunk_id="c1", content="apple banana", score=0.5),
            SearchResult(doc_id="d2", chunk_id="c2", content="cherry date", score=0.8),
        ]

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="[1, 0]")]
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        tools = RagTools(anthropic_client=mock_client)
        reranked = await tools.rerank_results("cherry", results)

        assert isinstance(reranked, list)
        assert len(reranked) == 2
        # cherry date should be first after reranking with [1, 0]
        assert reranked[0].chunk_id == "c2"

    @pytest.mark.asyncio
    async def test_no_anthropic_client_returns_original_order(self):
        results = [
            SearchResult(doc_id="d1", chunk_id="c1", content="text", score=0.5),
        ]
        tools = RagTools(anthropic_client=None)
        reranked = await tools.rerank_results("query", results)
        assert reranked == results

    @pytest.mark.asyncio
    async def test_empty_results_returns_empty(self):
        mock_client = AsyncMock()
        tools = RagTools(anthropic_client=mock_client)
        reranked = await tools.rerank_results("query", [])
        assert reranked == []
