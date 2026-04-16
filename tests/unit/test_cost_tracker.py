"""Tests for CostTracker — per-request cost computation and DB aggregation."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.cost_tracker import (
    CostTracker,
    RequestCost,
)


class TestComputeCostSonnet:
    """Cost computation for claude-sonnet-4-6."""

    def test_sonnet_input_cost_correct(self):
        tracker = CostTracker()
        result = tracker.compute_cost("claude-sonnet-4-6", 1000, 0, "extract", 100.0)
        assert result.input_cost_usd == Decimal("0.003")

    def test_sonnet_output_cost_correct(self):
        tracker = CostTracker()
        result = tracker.compute_cost("claude-sonnet-4-6", 0, 1000, "extract", 100.0)
        assert result.output_cost_usd == Decimal("0.015")

    def test_sonnet_total_cost_is_sum(self):
        tracker = CostTracker()
        result = tracker.compute_cost("claude-sonnet-4-6", 1000, 1000, "extract", 100.0)
        assert result.total_cost_usd == result.input_cost_usd + result.output_cost_usd
        assert result.total_cost_usd == Decimal("0.018")


class TestComputeCostHaiku:
    """Cost computation for claude-haiku-4-5 variant."""

    def test_haiku_input_cost_correct(self):
        tracker = CostTracker()
        result = tracker.compute_cost("claude-haiku-4-5", 1000, 0, "classify", 50.0)
        assert result.input_cost_usd == Decimal("0.00025")

    def test_haiku_output_cost_correct(self):
        tracker = CostTracker()
        result = tracker.compute_cost("claude-haiku-4-5", 0, 1000, "classify", 50.0)
        assert result.output_cost_usd == Decimal("0.00125")

    def test_haiku_cheaper_than_sonnet(self):
        tracker = CostTracker()
        haiku = tracker.compute_cost("claude-haiku-4-5", 500, 500, "classify", 50.0)
        sonnet = tracker.compute_cost("claude-sonnet-4-6", 500, 500, "extract", 100.0)
        assert haiku.total_cost_usd < sonnet.total_cost_usd


class TestComputeCostEdgeCases:
    """Edge cases for compute_cost."""

    def test_zero_tokens_zero_cost(self):
        tracker = CostTracker()
        result = tracker.compute_cost("claude-sonnet-4-6", 0, 0, "extract", 0.0)
        assert result.total_cost_usd == Decimal("0")
        assert result.input_cost_usd == Decimal("0")
        assert result.output_cost_usd == Decimal("0")

    def test_unknown_model_raises_value_error(self):
        tracker = CostTracker()
        with pytest.raises(ValueError, match="Unknown model"):
            tracker.compute_cost("gpt-4o", 100, 100, "extract", 50.0)

    def test_unknown_model_error_includes_model_name(self):
        tracker = CostTracker()
        with pytest.raises(ValueError, match="gpt-5"):
            tracker.compute_cost("gpt-5", 100, 100, "extract", 50.0)

    def test_returns_request_cost_dataclass(self):
        tracker = CostTracker()
        result = tracker.compute_cost("claude-haiku-4-5", 100, 50, "classify", 75.0)
        assert isinstance(result, RequestCost)
        assert result.model == "claude-haiku-4-5"
        assert result.operation == "classify"
        assert result.latency_ms == 75.0
        assert result.input_tokens == 100
        assert result.output_tokens == 50

    def test_decimal_precision_maintained(self):
        tracker = CostTracker()
        # 1 token at sonnet pricing: 0.003 / 1000 = 0.000003
        result = tracker.compute_cost("claude-sonnet-4-6", 1, 0, "extract", 10.0)
        assert result.input_cost_usd == Decimal("0.003") / Decimal("1000")
        # Should not lose precision vs float arithmetic
        assert result.input_cost_usd == Decimal("0.000003")

    def test_opus_pricing_correct(self):
        tracker = CostTracker()
        result = tracker.compute_cost("claude-opus-4-6", 1000, 1000, "extract", 200.0)
        assert result.input_cost_usd == Decimal("0.015")
        assert result.output_cost_usd == Decimal("0.075")
        assert result.total_cost_usd == Decimal("0.090")

    def test_gemini_embedding_zero_output_cost(self):
        tracker = CostTracker()
        result = tracker.compute_cost("gemini-embedding", 1000, 0, "embed", 20.0)
        assert result.output_cost_usd == Decimal("0")


class TestGetCostSummary:
    """Tests for get_cost_summary — mock DB queries."""

    @pytest.mark.asyncio
    async def test_groups_by_model_and_operation(self):
        tracker = CostTracker()
        mock_db = AsyncMock()

        # Two rows: same model, same operation
        row1 = MagicMock()
        row1.model = "claude-sonnet-4-6"
        row1.operation = "extract"
        row1.input_tokens = 500
        row1.output_tokens = 200

        row2 = MagicMock()
        row2.model = "claude-sonnet-4-6"
        row2.operation = "extract"
        row2.input_tokens = 500
        row2.output_tokens = 200

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [row1, row2]
        mock_db.execute = AsyncMock(return_value=mock_result)

        summary = await tracker.get_cost_summary(mock_db, days=7)

        assert "claude-sonnet-4-6" in summary
        assert "extract" in summary["claude-sonnet-4-6"]
        assert summary["claude-sonnet-4-6"]["extract"]["call_count"] == 2

    @pytest.mark.asyncio
    async def test_returns_avg_cost(self):
        tracker = CostTracker()
        mock_db = AsyncMock()

        row = MagicMock()
        row.model = "claude-haiku-4-5"
        row.operation = "classify"
        row.input_tokens = 1000
        row.output_tokens = 0

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [row]
        mock_db.execute = AsyncMock(return_value=mock_result)

        summary = await tracker.get_cost_summary(mock_db)
        op_data = summary["claude-haiku-4-5"]["classify"]

        # 1000 input tokens at haiku rate = 0.00025
        assert abs(op_data["total_cost"] - 0.00025) < 1e-9
        assert op_data["avg_cost"] == op_data["total_cost"]  # 1 call

    @pytest.mark.asyncio
    async def test_skips_unknown_models(self):
        tracker = CostTracker()
        mock_db = AsyncMock()

        row = MagicMock()
        row.model = "unknown-model-xyz"
        row.operation = "extract"
        row.input_tokens = 100
        row.output_tokens = 50

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [row]
        mock_db.execute = AsyncMock(return_value=mock_result)

        summary = await tracker.get_cost_summary(mock_db)
        assert "unknown-model-xyz" not in summary
