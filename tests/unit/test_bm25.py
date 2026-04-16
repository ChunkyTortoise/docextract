"""Unit tests for BM25 search service."""
from __future__ import annotations

from app.services.bm25 import _tokenize, build_index, search_bm25


class TestTokenize:
    def test_lowercases_and_splits(self):
        tokens = _tokenize("Hello World")
        assert tokens == ["hello", "world"]

    def test_removes_punctuation(self):
        tokens = _tokenize("INV-2024-0042, total: $500.00")
        assert "inv" in tokens or "2024" in tokens
        assert "$" not in tokens

    def test_empty_string(self):
        assert _tokenize("") == []


class TestBuildIndex:
    def test_returns_bm25_okapi(self):
        from rank_bm25 import BM25Okapi
        index = build_index(["hello world", "foo bar"])
        assert isinstance(index, BM25Okapi)

    def test_single_document(self):
        index = build_index(["only document"])
        assert index is not None

    def test_empty_list(self):
        from rank_bm25 import BM25Okapi
        index = build_index([])
        assert isinstance(index, BM25Okapi)


class TestSearchBM25:
    def test_exact_match_scores_highest(self):
        texts = [
            "Invoice INV-2024-0042 from Acme Corp",
            "Receipt from coffee shop total 5 dollars",
            "Bank statement account 12345",
        ]
        ids = ["r1", "r2", "r3"]
        index = build_index(texts)
        results = search_bm25("INV-2024-0042", index, ids, limit=3)
        assert len(results) > 0
        assert results[0][0] == "r1"

    def test_no_match_returns_empty(self):
        texts = ["hello world", "foo bar"]
        ids = ["r1", "r2"]
        index = build_index(texts)
        results = search_bm25("zzz xyz nonsense", index, ids, limit=10)
        assert results == []

    def test_returns_at_most_limit_results(self):
        texts = [f"document number {i} invoice" for i in range(20)]
        ids = [f"r{i}" for i in range(20)]
        index = build_index(texts)
        results = search_bm25("invoice", index, ids, limit=5)
        assert len(results) <= 5

    def test_empty_query_returns_empty(self):
        texts = ["hello world"]
        ids = ["r1"]
        index = build_index(texts)
        results = search_bm25("", index, ids, limit=10)
        assert results == []

    def test_results_sorted_by_score_desc(self):
        texts = [
            "invoice invoice invoice",  # most relevant
            "invoice receipt",           # medium
            "bank statement",            # not relevant
        ]
        ids = ["r1", "r2", "r3"]
        index = build_index(texts)
        results = search_bm25("invoice", index, ids, limit=3)
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_scores_are_positive(self):
        texts = ["invoice from Acme", "purchase order"]
        ids = ["r1", "r2"]
        index = build_index(texts)
        results = search_bm25("invoice", index, ids, limit=2)
        for _, score in results:
            assert score > 0
