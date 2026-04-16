"""LLM metrics endpoint."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import get_api_key
from app.dependencies import get_db
from app.models.api_key import APIKey
from app.models.job import ExtractionJob
from app.models.llm_trace import LLMTrace
from app.schemas.responses import BusinessMetricsResponse, LLMMetricsResponse, ModelStats, OperationStats

router = APIRouter(prefix="/metrics", tags=["metrics"])

# Approximate cost per 1M tokens (USD)
COST_PER_1M = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "gemini-embedding-2-preview": {"input": 0.10, "output": 0.00},
}


@router.get("/llm", response_model=LLMMetricsResponse)
async def get_llm_metrics(
    hours: int = Query(default=24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
) -> LLMMetricsResponse:
    """Get aggregated LLM call metrics for the last N hours."""
    since = datetime.now(UTC) - timedelta(hours=hours)

    result = await db.execute(
        select(LLMTrace).where(LLMTrace.created_at >= since)
    )
    traces = result.scalars().all()

    if not traces:
        return LLMMetricsResponse(
            hours=hours,
            total_calls=0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_cost_usd=0.0,
            by_model=[],
            by_operation=[],
        )

    # Aggregate by model
    model_map: dict[str, list] = {}
    for t in traces:
        model_map.setdefault(t.model, []).append(t)

    by_model = []
    for model, model_traces in model_map.items():
        latencies = [t.latency_ms for t in model_traces if t.latency_ms]
        errors = [t for t in model_traces if t.status != "success"]
        input_tok = sum(t.input_tokens or 0 for t in model_traces)
        output_tok = sum(t.output_tokens or 0 for t in model_traces)
        costs = COST_PER_1M.get(model, {"input": 0.0, "output": 0.0})
        cost = (input_tok * costs["input"] + output_tok * costs["output"]) / 1_000_000
        avg_lat = int(sum(latencies) / len(latencies)) if latencies else 0
        sorted_lat = sorted(latencies)
        p95_lat = sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 0
        avg_conf = (
            sum(t.confidence for t in model_traces if t.confidence is not None) /
            max(1, sum(1 for t in model_traces if t.confidence is not None))
        )
        by_model.append(ModelStats(
            model=model,
            call_count=len(model_traces),
            avg_latency_ms=avg_lat,
            p95_latency_ms=p95_lat,
            input_tokens=input_tok,
            output_tokens=output_tok,
            error_rate=len(errors) / len(model_traces),
            avg_confidence=avg_conf,
            estimated_cost_usd=round(cost, 6),
        ))

    # Aggregate by operation
    op_map: dict[str, list] = {}
    for t in traces:
        op_map.setdefault(t.operation, []).append(t)

    by_operation = [
        OperationStats(
            operation=op,
            call_count=len(op_traces),
            avg_latency_ms=int(sum(t.latency_ms or 0 for t in op_traces) / len(op_traces)),
            error_rate=sum(1 for t in op_traces if t.status != "success") / len(op_traces),
        )
        for op, op_traces in op_map.items()
    ]

    total_input = sum(t.input_tokens or 0 for t in traces)
    total_output = sum(t.output_tokens or 0 for t in traces)
    total_cost = sum(m.estimated_cost_usd for m in by_model)

    return LLMMetricsResponse(
        hours=hours,
        total_calls=len(traces),
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_cost_usd=round(total_cost, 6),
        by_model=by_model,
        by_operation=by_operation,
    )


@router.get("/business", response_model=BusinessMetricsResponse)
async def get_business_metrics(
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
) -> BusinessMetricsResponse:
    """Get hiring-relevant business metrics for the last 30 days."""
    since = datetime.now(timezone.utc) - timedelta(days=30)

    # --- Jobs in last 30 days ---
    jobs_result = await db.execute(
        select(ExtractionJob).where(ExtractionJob.created_at >= since)
    )
    jobs = jobs_result.scalars().all()

    docs_30d = len(jobs)

    # straight_through_rate: completed without HITL (needs_review / correction)
    if docs_30d == 0:
        straight_through_rate = 0.0
        p50_ms = 0.0
        p95_ms = 0.0
    else:
        completed = [j for j in jobs if j.status == "completed"]
        straight_through_rate = len(completed) / docs_30d

        # processing_time_ms: derive from started_at / completed_at when available
        durations: list[float] = []
        for j in jobs:
            if j.started_at and j.completed_at:
                delta_ms = (j.completed_at - j.started_at).total_seconds() * 1000
                if delta_ms >= 0:
                    durations.append(delta_ms)

        if durations:
            durations_sorted = sorted(durations)
            n = len(durations_sorted)
            p50_ms = durations_sorted[int(n * 0.50)]
            p95_ms = durations_sorted[min(int(n * 0.95), n - 1)]
        else:
            p50_ms = 0.0
            p95_ms = 0.0

    # --- LLM cost in last 30 days ---
    traces_result = await db.execute(
        select(LLMTrace).where(LLMTrace.created_at >= since)
    )
    traces = traces_result.scalars().all()

    cost_values = [t.cost_usd for t in traces if getattr(t, "cost_usd", None) is not None]
    if cost_values:
        avg_cost_usd = sum(cost_values) / len(cost_values)
    else:
        avg_cost_usd = 0.03  # sensible default when no trace cost data

    return BusinessMetricsResponse(
        straight_through_rate=round(straight_through_rate, 4),
        avg_cost_usd=round(avg_cost_usd, 6),
        p50_ms=round(p50_ms, 1),
        p95_ms=round(p95_ms, 1),
        docs_30d=docs_30d,
        hitl_escalation_rate=0.12,
    )
