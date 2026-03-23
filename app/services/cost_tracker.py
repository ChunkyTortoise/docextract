"""Per-request LLM cost computation and aggregation from llm_traces table."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Claude API pricing (as of 2026) — cost per 1,000 tokens in USD
COST_PER_1K_TOKENS: dict[str, dict[str, Decimal]] = {
    "claude-sonnet-4-6": {
        "input": Decimal("0.003"),
        "output": Decimal("0.015"),
    },
    "claude-haiku-4-5": {
        "input": Decimal("0.00025"),
        "output": Decimal("0.00125"),
    },
    # Haiku version variants used in model chains
    "claude-haiku-4-5-20251001": {
        "input": Decimal("0.00025"),
        "output": Decimal("0.00125"),
    },
    "claude-opus-4-6": {
        "input": Decimal("0.015"),
        "output": Decimal("0.075"),
    },
    # Gemini for embeddings (approximate)
    "gemini-embedding": {
        "input": Decimal("0.00001"),
        "output": Decimal("0.0"),
    },
}


@dataclass
class RequestCost:
    """Cost breakdown for a single LLM API call."""

    model: str
    input_tokens: int
    output_tokens: int
    input_cost_usd: Decimal
    output_cost_usd: Decimal
    total_cost_usd: Decimal
    operation: str  # e.g. "extract", "classify", "rerank"
    latency_ms: float


class CostTracker:
    """Tracks per-request token costs and exposes comparison data."""

    def compute_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        operation: str,
        latency_ms: float,
    ) -> RequestCost:
        """Compute cost in USD for a single LLM call.

        Args:
            model: Model identifier (must exist in COST_PER_1K_TOKENS).
            input_tokens: Number of input/prompt tokens consumed.
            output_tokens: Number of output/completion tokens generated.
            operation: Logical operation name for grouping (e.g. "extract").
            latency_ms: Wall-clock latency of the call in milliseconds.

        Returns:
            RequestCost dataclass with per-direction and total costs.

        Raises:
            ValueError: When model is not found in the pricing table.
        """
        pricing = COST_PER_1K_TOKENS.get(model)
        if pricing is None:
            raise ValueError(
                f"Unknown model '{model}'. "
                f"Known models: {list(COST_PER_1K_TOKENS.keys())}"
            )

        input_cost = Decimal(input_tokens) * pricing["input"] / Decimal("1000")
        output_cost = Decimal(output_tokens) * pricing["output"] / Decimal("1000")

        return RequestCost(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_cost_usd=input_cost,
            output_cost_usd=output_cost,
            total_cost_usd=input_cost + output_cost,
            operation=operation,
            latency_ms=latency_ms,
        )

    async def get_cost_summary(self, db: "AsyncSession", days: int = 7) -> dict:
        """Get cost summary from llm_traces table aggregated by model and operation.

        Queries the existing llm_traces table (populated by trace_llm_call) and
        applies COST_PER_1K_TOKENS pricing to compute USD costs per row.

        Args:
            db: Active async SQLAlchemy session.
            days: Lookback window in days.

        Returns:
            Nested dict: {model: {operation: {total_cost, avg_cost, call_count}}}
        """
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select, text

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Fetch traces within the window that have token data
        stmt = text(
            """
            SELECT model, operation, input_tokens, output_tokens
            FROM llm_traces
            WHERE created_at >= :cutoff
              AND input_tokens IS NOT NULL
              AND output_tokens IS NOT NULL
            """
        )
        result = await db.execute(stmt, {"cutoff": cutoff})
        rows = result.fetchall()

        summary: dict[str, dict[str, dict]] = {}
        for row in rows:
            model, operation = row.model, row.operation
            pricing = COST_PER_1K_TOKENS.get(model)
            if pricing is None:
                continue

            cost = (
                Decimal(row.input_tokens) * pricing["input"] / Decimal("1000")
                + Decimal(row.output_tokens) * pricing["output"] / Decimal("1000")
            )

            if model not in summary:
                summary[model] = {}
            if operation not in summary[model]:
                summary[model][operation] = {
                    "total_cost": Decimal("0"),
                    "call_count": 0,
                }

            summary[model][operation]["total_cost"] += cost
            summary[model][operation]["call_count"] += 1

        # Compute averages
        for model_data in summary.values():
            for op_data in model_data.values():
                count = op_data["call_count"]
                op_data["avg_cost"] = (
                    op_data["total_cost"] / count if count > 0 else Decimal("0")
                )
                # Convert Decimals to float for JSON serialisation friendliness
                op_data["total_cost"] = float(op_data["total_cost"])
                op_data["avg_cost"] = float(op_data["avg_cost"])

        return summary

    async def get_model_comparison(self, db: "AsyncSession", days: int = 7) -> list[dict]:
        """Compare cost vs latency across models for the same operations.

        Args:
            db: Active async SQLAlchemy session.
            days: Lookback window in days.

        Returns:
            List of dicts with keys: model, operation, avg_cost, avg_latency, call_count.
        """
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import text

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = text(
            """
            SELECT model, operation,
                   AVG(latency_ms)   AS avg_latency,
                   AVG(input_tokens) AS avg_input,
                   AVG(output_tokens) AS avg_output,
                   COUNT(*)           AS call_count
            FROM llm_traces
            WHERE created_at >= :cutoff
              AND input_tokens IS NOT NULL
              AND output_tokens IS NOT NULL
            GROUP BY model, operation
            ORDER BY model, operation
            """
        )
        result = await db.execute(stmt, {"cutoff": cutoff})
        rows = result.fetchall()

        comparison: list[dict] = []
        for row in rows:
            pricing = COST_PER_1K_TOKENS.get(row.model)
            if pricing is None:
                avg_cost = 0.0
            else:
                avg_cost = float(
                    Decimal(str(row.avg_input)) * pricing["input"] / Decimal("1000")
                    + Decimal(str(row.avg_output)) * pricing["output"] / Decimal("1000")
                )

            comparison.append(
                {
                    "model": row.model,
                    "operation": row.operation,
                    "avg_cost": avg_cost,
                    "avg_latency": float(row.avg_latency or 0),
                    "call_count": int(row.call_count),
                }
            )

        return comparison
