"""TF-IDF cross-score reranker for RAG result re-ranking.

Replaces the no-op stub in agentic_rag._execute_tool("rerank_results").
Uses TF-IDF cosine similarity to score query-document relevance, then
combines with the existing RRF score from hybrid retrieval.

No external API key required — pure scikit-learn.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

if TYPE_CHECKING:
    from app.services.rag_tools import SearchResult

logger = logging.getLogger(__name__)


class TFIDFReranker:
    """Cross-score reranker using TF-IDF cosine similarity.

    Combines the query-document TF-IDF similarity with the retrieval score
    (RRF or vector cosine distance) using a weighted blend.

    Args:
        alpha: Weight for TF-IDF similarity (0.0–1.0).
               The retrieval score weight is (1 - alpha).
               Default 0.4 gives moderate boost to lexical match signal.
    """

    def __init__(self, alpha: float = 0.4) -> None:
        self.alpha = alpha
        self._vectorizer = TfidfVectorizer(
            lowercase=True,
            stop_words="english",
            max_features=10_000,
            ngram_range=(1, 2),
        )

    def rerank(
        self,
        query: str,
        results: "list[SearchResult]",
        top_k: int | None = None,
    ) -> "list[SearchResult]":
        """Return results re-sorted by combined relevance score.

        Args:
            query: The search query.
            results: Candidate results from vector/BM25/hybrid retrieval.
            top_k: Return at most this many results (None = return all).

        Returns:
            Re-sorted results, highest score first.
        """
        if not results:
            return results

        corpus = [query] + [r.content for r in results]
        try:
            tfidf_matrix = self._vectorizer.fit_transform(corpus)
        except ValueError as e:
            logger.warning("TFIDFReranker fit failed (%s) — returning original order", e)
            return results[:top_k] if top_k else results

        query_vec = tfidf_matrix[0:1]
        doc_vecs = tfidf_matrix[1:]
        tfidf_scores = cosine_similarity(query_vec, doc_vecs).flatten()

        # Normalize existing retrieval scores to [0, 1]
        raw_scores = np.array([r.score for r in results], dtype=float)
        score_range = raw_scores.max() - raw_scores.min()
        if score_range > 0:
            norm_scores = (raw_scores - raw_scores.min()) / score_range
        else:
            norm_scores = np.ones(len(results))

        combined = self.alpha * tfidf_scores + (1.0 - self.alpha) * norm_scores
        ranked_indices = combined.argsort()[::-1]

        reranked = []
        for idx in ranked_indices:
            result = results[idx]
            result.score = float(combined[idx])
            reranked.append(result)

        logger.debug(
            "Reranked %d results — top score %.3f (tfidf=%.3f retrieval=%.3f)",
            len(results),
            combined[ranked_indices[0]],
            tfidf_scores[ranked_indices[0]],
            norm_scores[ranked_indices[0]],
        )

        return reranked[:top_k] if top_k else reranked
