"""Unit tests for semantic caching layer."""
from __future__ import annotations

import time
import numpy as np
import pytest

from app.services.semantic_cache import CacheResult, CacheStats, SemanticCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_embedding(dim: int = 768, seed: int = 42) -> list[float]:
    rng = np.random.RandomState(seed)
    vec = rng.randn(dim).astype(np.float32)
    vec = vec / np.linalg.norm(vec)
    return vec.tolist()


def _similar_embedding(base: list[float], noise: float = 0.01, seed: int = 99) -> list[float]:
    """Create a vector similar to base (high cosine similarity)."""
    rng = np.random.RandomState(seed)
    base_arr = np.array(base, dtype=np.float32)
    perturbed = base_arr + rng.randn(len(base)).astype(np.float32) * noise
    perturbed = perturbed / np.linalg.norm(perturbed)
    return perturbed.tolist()


def _orthogonal_embedding(dim: int = 768, seed: int = 123) -> list[float]:
    """Create a vector likely dissimilar to standard random embeddings."""
    rng = np.random.RandomState(seed)
    vec = rng.randn(dim).astype(np.float32)
    vec = vec / np.linalg.norm(vec)
    return vec.tolist()


# ---------------------------------------------------------------------------
# Cache miss on empty cache
# ---------------------------------------------------------------------------

class TestCacheMiss:
    def test_empty_cache_returns_miss(self):
        cache = SemanticCache()
        result = cache.get(_random_embedding())
        assert result.hit is False
        assert result.response is None

    def test_miss_increments_counter(self):
        cache = SemanticCache()
        cache.get(_random_embedding())
        stats = cache.get_stats()
        assert stats.misses == 1
        assert stats.hits == 0


# ---------------------------------------------------------------------------
# Cache hit on identical prompt
# ---------------------------------------------------------------------------

class TestCacheHit:
    def test_hit_on_identical_embedding(self):
        cache = SemanticCache(similarity_threshold=0.95)
        emb = _random_embedding()
        cache.put(embedding=emb, response="cached answer", model="test", cost_usd=0.01)

        result = cache.get(emb)
        assert result.hit is True
        assert result.response == "cached answer"
        assert result.similarity >= 0.99

    def test_hit_on_semantically_similar_embedding(self):
        cache = SemanticCache(similarity_threshold=0.95)
        base_emb = _random_embedding()
        similar_emb = _similar_embedding(base_emb, noise=0.01)

        cache.put(embedding=base_emb, response="cached", model="test", cost_usd=0.02)
        result = cache.get(similar_emb)

        assert result.hit is True
        assert result.similarity >= 0.95

    def test_miss_on_dissimilar_embedding(self):
        cache = SemanticCache(similarity_threshold=0.95)
        cache.put(
            embedding=_random_embedding(seed=1),
            response="first", model="test", cost_usd=0.01,
        )
        result = cache.get(_orthogonal_embedding())
        assert result.hit is False

    def test_hit_increments_counter(self):
        cache = SemanticCache(similarity_threshold=0.95)
        emb = _random_embedding()
        cache.put(embedding=emb, response="answer", cost_usd=0.05)
        cache.get(emb)

        stats = cache.get_stats()
        assert stats.hits == 1
        assert stats.misses == 0


# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------

class TestCostTracking:
    def test_cost_saved_accumulated(self):
        cache = SemanticCache(similarity_threshold=0.90)
        emb = _random_embedding()
        cache.put(embedding=emb, response="ans", cost_usd=0.05)

        # Hit three times
        for _ in range(3):
            cache.get(emb)

        stats = cache.get_stats()
        assert stats.total_cost_saved_usd == pytest.approx(0.15, abs=0.001)

    def test_cache_result_includes_cost(self):
        cache = SemanticCache(similarity_threshold=0.90)
        emb = _random_embedding()
        cache.put(embedding=emb, response="ans", cost_usd=0.03)

        result = cache.get(emb)
        assert result.cost_saved_usd == pytest.approx(0.03)


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------

class TestTTLExpiry:
    def test_expired_entries_evicted(self):
        cache = SemanticCache(similarity_threshold=0.90, ttl_seconds=1)
        emb = _random_embedding()
        cache.put(embedding=emb, response="old", cost_usd=0.01)

        # Manually expire
        cache._entries[0].created_at = time.time() - 2

        result = cache.get(emb)
        assert result.hit is False
        assert cache.get_stats().total_entries == 0


# ---------------------------------------------------------------------------
# Max entries (FIFO eviction)
# ---------------------------------------------------------------------------

class TestMaxEntries:
    def test_fifo_eviction_on_overflow(self):
        cache = SemanticCache(max_entries=3)
        for i in range(5):
            cache.put(
                embedding=_random_embedding(seed=i),
                response=f"entry-{i}",
            )
        assert cache.get_stats().total_entries == 3


# ---------------------------------------------------------------------------
# Stats endpoint
# ---------------------------------------------------------------------------

class TestCacheStats:
    def test_stats_default_empty(self):
        cache = SemanticCache()
        stats = cache.get_stats()
        assert stats.total_entries == 0
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.hit_rate == 0.0

    def test_hit_rate_calculated(self):
        cache = SemanticCache(similarity_threshold=0.90)
        emb = _random_embedding()
        cache.put(embedding=emb, response="x", cost_usd=0.01)

        cache.get(emb)  # hit
        cache.get(_orthogonal_embedding())  # miss

        stats = cache.get_stats()
        assert stats.hit_rate == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------

class TestCacheClear:
    def test_clear_resets_everything(self):
        cache = SemanticCache()
        emb = _random_embedding()
        cache.put(embedding=emb, response="x")
        cache.get(emb)
        cache.clear()

        stats = cache.get_stats()
        assert stats.total_entries == 0
        assert stats.hits == 0
        assert stats.misses == 0


# ---------------------------------------------------------------------------
# Put returns cache_id
# ---------------------------------------------------------------------------

class TestPut:
    def test_put_returns_cache_id(self):
        cache = SemanticCache()
        cache_id = cache.put(embedding=_random_embedding(), response="x")
        assert isinstance(cache_id, str)
        assert len(cache_id) == 12

    def test_multiple_puts_grow_cache(self):
        cache = SemanticCache()
        for i in range(5):
            cache.put(embedding=_random_embedding(seed=i), response=f"r{i}")
        assert cache.get_stats().total_entries == 5
