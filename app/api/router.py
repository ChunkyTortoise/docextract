"""Central API router -- includes all route modules."""
from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    agent_eval,
    agent_search,
    api_keys,
    cache_stats,
    documents,
    export,
    extract_structured,
    feedback,
    finetune_export,
    health,
    jobs,
    metrics,
    records,
    review,
    roi,
    stats,
    webhooks,
)

api_router = APIRouter(prefix="/api/v1")

# Health -- no auth
api_router.include_router(health.router)

# Authed routes
api_router.include_router(documents.router)
api_router.include_router(jobs.router)
api_router.include_router(export.router)
api_router.include_router(records.router)
api_router.include_router(webhooks.router)
api_router.include_router(stats.router)
api_router.include_router(api_keys.router)
api_router.include_router(review.router)
api_router.include_router(roi.router)
api_router.include_router(metrics.router)
api_router.include_router(agent_search.router)
api_router.include_router(agent_eval.router)
api_router.include_router(extract_structured.router)
api_router.include_router(feedback.router)
api_router.include_router(finetune_export.router)
api_router.include_router(cache_stats.router)
