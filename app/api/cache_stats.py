"""Semantic cache statistics endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.middleware import get_api_key
from app.models.api_key import APIKey
from app.services.semantic_cache import CacheStats

router = APIRouter(tags=["cache"])


# Module-level cache instance (singleton, populated by app startup)
_cache_instance = None


def set_cache_instance(cache) -> None:
    """Register the global SemanticCache instance for the stats endpoint."""
    global _cache_instance
    _cache_instance = cache


@router.get("/cache/stats", response_model=CacheStats)
async def cache_stats(
    api_key: APIKey = Depends(get_api_key),
) -> CacheStats:
    """Return semantic cache hit/miss stats and cost savings."""
    from app.services.semantic_cache import CacheStats

    if _cache_instance is None:
        return CacheStats(
            total_entries=0, hits=0, misses=0,
            hit_rate=0.0, total_cost_saved_usd=0.0,
        )
    return _cache_instance.get_stats()
