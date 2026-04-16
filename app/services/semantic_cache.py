"""Semantic caching layer for LLM responses.

Caches extraction and RAG responses keyed by embedding similarity rather than
exact string match. When a new request arrives, embed the prompt, search cached
embeddings with cosine similarity, and return the cached response if similarity
exceeds a configurable threshold.

Feature-flagged via SEMANTIC_CACHE_ENABLED (default false).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time

import numpy as np
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class CacheEntry(BaseModel):
    """Single cache entry with embedding, response, and metadata."""
    cache_id: str
    embedding: list[float]
    response: str
    model: str
    cost_usd: float
    created_at: float  # Unix timestamp


class CacheResult(BaseModel):
    """Result of a cache lookup."""
    hit: bool
    response: str | None = None
    similarity: float = 0.0
    cost_saved_usd: float = 0.0
    cache_id: str | None = None


class CacheStats(BaseModel):
    """Aggregate cache statistics."""
    total_entries: int
    hits: int
    misses: int
    hit_rate: float
    total_cost_saved_usd: float


class SemanticCache:
    """In-memory semantic cache with cosine similarity lookup.

    Entries are stored as numpy arrays for fast batch cosine distance
    computation. Supports up to ~50K entries at sub-millisecond latency.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.95,
        ttl_seconds: int = 3600,
        max_entries: int = 10_000,
    ) -> None:
        self._threshold = similarity_threshold
        self._ttl = ttl_seconds
        self._max_entries = max_entries

        # In-memory store
        self._entries: list[CacheEntry] = []
        self._embeddings: np.ndarray | None = None  # (N, dim) matrix

        # Stats counters
        self._hits = 0
        self._misses = 0
        self._cost_saved = 0.0

    def get(self, query_embedding: list[float]) -> CacheResult:
        """Look up the cache for a semantically similar prompt.

        Returns a CacheResult with hit=True if similarity exceeds threshold.
        """
        self._evict_expired()

        if not self._entries or self._embeddings is None:
            self._misses += 1
            return CacheResult(hit=False)

        query_vec = np.array(query_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            self._misses += 1
            return CacheResult(hit=False)
        query_vec = query_vec / query_norm

        # Cosine similarity = dot product of normalized vectors
        norms = np.linalg.norm(self._embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)  # avoid div by zero
        normalized = self._embeddings / norms
        similarities = normalized @ query_vec

        best_idx = int(np.argmax(similarities))
        best_sim = float(similarities[best_idx])

        if best_sim >= self._threshold:
            entry = self._entries[best_idx]
            self._hits += 1
            self._cost_saved += entry.cost_usd
            return CacheResult(
                hit=True,
                response=entry.response,
                similarity=best_sim,
                cost_saved_usd=entry.cost_usd,
                cache_id=entry.cache_id,
            )

        self._misses += 1
        return CacheResult(hit=False, similarity=best_sim)

    def put(
        self,
        embedding: list[float],
        response: str,
        model: str = "",
        cost_usd: float = 0.0,
    ) -> str:
        """Store a new cache entry. Returns the cache_id."""
        cache_id = hashlib.md5(
            json.dumps(embedding[:16], default=str).encode()
        ).hexdigest()[:12]

        entry = CacheEntry(
            cache_id=cache_id,
            embedding=embedding,
            response=response,
            model=model,
            cost_usd=cost_usd,
            created_at=time.time(),
        )

        self._entries.append(entry)

        # Rebuild numpy matrix
        vec = np.array(embedding, dtype=np.float32).reshape(1, -1)
        if self._embeddings is None:
            self._embeddings = vec
        else:
            self._embeddings = np.vstack([self._embeddings, vec])

        # Enforce max entries (FIFO eviction)
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]
            self._embeddings = self._embeddings[-self._max_entries:]

        return cache_id

    def get_stats(self) -> CacheStats:
        """Return aggregate cache statistics."""
        total_requests = self._hits + self._misses
        return CacheStats(
            total_entries=len(self._entries),
            hits=self._hits,
            misses=self._misses,
            hit_rate=self._hits / total_requests if total_requests > 0 else 0.0,
            total_cost_saved_usd=round(self._cost_saved, 4),
        )

    def clear(self) -> None:
        """Clear all cache entries and reset stats."""
        self._entries.clear()
        self._embeddings = None
        self._hits = 0
        self._misses = 0
        self._cost_saved = 0.0

    def _evict_expired(self) -> None:
        """Remove entries older than TTL."""
        if not self._entries:
            return
        now = time.time()
        cutoff = now - self._ttl
        # Find first non-expired entry (entries are in insertion order)
        first_valid = 0
        for i, entry in enumerate(self._entries):
            if entry.created_at >= cutoff:
                first_valid = i
                break
        else:
            # All expired
            self.clear()
            return

        if first_valid > 0:
            self._entries = self._entries[first_valid:]
            if self._embeddings is not None:
                self._embeddings = self._embeddings[first_valid:]
