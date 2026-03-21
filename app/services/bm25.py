"""BM25 text search index for hybrid search."""
from __future__ import annotations

import re
from typing import Any

from rank_bm25 import BM25Okapi


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    return re.findall(r"\b\w+\b", text.lower())


def build_index(texts: list[str]) -> BM25Okapi:
    """Build a BM25Okapi index from a list of text strings.

    Handles empty corpus by providing a placeholder document so BM25Okapi
    does not raise ZeroDivisionError; the placeholder has no effect on
    real queries because search_bm25 filters by score > 0.
    """
    tokenized = [_tokenize(t) for t in texts] if texts else [["__empty__"]]
    return BM25Okapi(tokenized)


def search_bm25(
    query: str,
    index: BM25Okapi,
    record_ids: list[str],
    limit: int = 10,
) -> list[tuple[str, float]]:
    """Search BM25 index, return (record_id, score) pairs sorted by score desc.

    Returns up to `limit` results with score > 0.
    """
    tokens = _tokenize(query)
    if not tokens:
        return []
    scores = index.get_scores(tokens)
    ranked = sorted(
        zip(record_ids, scores),
        key=lambda x: x[1],
        reverse=True,
    )
    return [(rid, score) for rid, score in ranked[:limit] if score > 0]
