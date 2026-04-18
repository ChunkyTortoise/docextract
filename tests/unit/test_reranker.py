"""Unit tests for TFIDFReranker."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.reranker import TFIDFReranker


def _make_result(content: str, score: float = 0.5) -> MagicMock:
    r = MagicMock()
    r.content = content
    r.score = score
    return r


class TestTFIDFReranker:
    def test_rerank_returns_same_count(self):
        reranker = TFIDFReranker()
        results = [
            _make_result("invoice from acme corp", 0.9),
            _make_result("unrelated weather report", 0.8),
            _make_result("vendor payment terms net 30", 0.7),
        ]
        reranked = reranker.rerank("invoice vendor payment", results)
        assert len(reranked) == 3

    def test_rerank_top_k(self):
        reranker = TFIDFReranker()
        results = [_make_result(f"doc {i}", float(i) / 10) for i in range(10)]
        reranked = reranker.rerank("query", results, top_k=3)
        assert len(reranked) == 3

    def test_rerank_empty_input(self):
        reranker = TFIDFReranker()
        assert reranker.rerank("query", []) == []

    def test_rerank_scores_are_updated(self):
        # With alpha=0.9 TF-IDF dominates; invoice doc should beat high-retrieval unrelated doc
        reranker = TFIDFReranker(alpha=0.9)
        results = [
            _make_result("invoice acme corp 1000 dollars", 0.1),
            _make_result("completely unrelated astronomy paper", 0.9),
        ]
        reranked = reranker.rerank("invoice acme corp", results)
        assert "invoice" in reranked[0].content or "acme" in reranked[0].content

    def test_rerank_single_result(self):
        reranker = TFIDFReranker()
        result = _make_result("single document", 0.7)
        reranked = reranker.rerank("query", [result])
        assert len(reranked) == 1

    def test_alpha_weighting(self):
        """With alpha=1.0, only TF-IDF matters; with alpha=0, only retrieval score."""
        # High TF-IDF alpha: "exact" query match should win despite low retrieval score
        results_tfidf = [
            _make_result("exact query match text", 0.1),
            _make_result("unrelated document here", 0.9),
        ]
        reranked = TFIDFReranker(alpha=1.0).rerank("exact query match text", results_tfidf)
        assert "exact" in reranked[0].content

        # Zero TF-IDF alpha: only retrieval score matters, "unrelated" wins
        results_retrieval = [
            _make_result("exact query match text", 0.1),
            _make_result("unrelated document here", 0.9),
        ]
        reranked2 = TFIDFReranker(alpha=0.0).rerank("exact query match text", results_retrieval)
        assert "unrelated" in reranked2[0].content
