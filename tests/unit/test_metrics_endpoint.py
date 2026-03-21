"""Tests for LLM metrics endpoint."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.responses import LLMMetricsResponse, ModelStats, OperationStats


class TestLLMMetricsResponseSchema:
    def test_valid_response(self):
        resp = LLMMetricsResponse(
            hours=24,
            total_calls=100,
            total_input_tokens=5000,
            total_output_tokens=2000,
            total_cost_usd=0.015,
            by_model=[],
            by_operation=[],
        )
        assert resp.hours == 24
        assert resp.total_calls == 100

    def test_model_stats(self):
        stats = ModelStats(
            model="claude-sonnet-4-6",
            call_count=50,
            avg_latency_ms=1200,
            p95_latency_ms=2000,
            input_tokens=3000,
            output_tokens=1500,
            error_rate=0.02,
            avg_confidence=0.88,
            estimated_cost_usd=0.013,
        )
        assert stats.model == "claude-sonnet-4-6"
        assert stats.call_count == 50

    def test_operation_stats(self):
        stats = OperationStats(
            operation="extract",
            call_count=40,
            avg_latency_ms=1100,
            error_rate=0.0,
        )
        assert stats.operation == "extract"

    def test_empty_lists(self):
        resp = LLMMetricsResponse(
            hours=24,
            total_calls=0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_cost_usd=0.0,
            by_model=[],
            by_operation=[],
        )
        assert resp.by_model == []
        assert resp.by_operation == []


class TestMetricsEndpointIntegration:
    """Test metrics endpoint using mock DB."""

    def _make_mock_trace(self, model="claude-sonnet-4-6", operation="extract",
                         status="success", latency_ms=1000, input_tokens=100,
                         output_tokens=50, confidence=0.9):
        t = MagicMock()
        t.model = model
        t.operation = operation
        t.status = status
        t.latency_ms = latency_ms
        t.input_tokens = input_tokens
        t.output_tokens = output_tokens
        t.confidence = confidence
        return t

    @pytest.mark.asyncio
    async def test_empty_db_returns_zero_metrics(self):
        """Test the aggregation logic directly."""
        from app.api.metrics import get_llm_metrics
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_api_key = MagicMock()
        response = await get_llm_metrics(hours=24, db=mock_db, api_key=mock_api_key)

        assert response.total_calls == 0
        assert response.total_input_tokens == 0
        assert response.total_cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_seeded_traces_aggregated(self):
        from app.api.metrics import get_llm_metrics
        traces = [
            self._make_mock_trace("claude-sonnet-4-6", "extract", "success", 1000, 200, 100, 0.9),
            self._make_mock_trace("claude-sonnet-4-6", "extract", "success", 1200, 300, 150, 0.85),
            self._make_mock_trace("claude-haiku-4-5-20251001", "classify", "success", 200, 50, 20, 0.95),
        ]
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = traces
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_api_key = MagicMock()
        response = await get_llm_metrics(hours=24, db=mock_db, api_key=mock_api_key)

        assert response.total_calls == 3
        assert response.total_input_tokens == 550
        assert len(response.by_model) == 2

    @pytest.mark.asyncio
    async def test_error_traces_counted_in_error_rate(self):
        from app.api.metrics import get_llm_metrics
        traces = [
            self._make_mock_trace(status="success"),
            self._make_mock_trace(status="error"),
        ]
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = traces
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_api_key = MagicMock()
        response = await get_llm_metrics(hours=24, db=mock_db, api_key=mock_api_key)

        model_stat = response.by_model[0]
        assert model_stat.error_rate == 0.5

    @pytest.mark.asyncio
    async def test_by_operation_breakdown(self):
        from app.api.metrics import get_llm_metrics
        traces = [
            self._make_mock_trace(operation="extract"),
            self._make_mock_trace(operation="classify"),
            self._make_mock_trace(operation="extract"),
        ]
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = traces
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_api_key = MagicMock()
        response = await get_llm_metrics(hours=24, db=mock_db, api_key=mock_api_key)

        ops = {op.operation: op for op in response.by_operation}
        assert "extract" in ops
        assert ops["extract"].call_count == 2

    @pytest.mark.asyncio
    async def test_cost_calculation_nonzero(self):
        from app.api.metrics import get_llm_metrics
        traces = [
            self._make_mock_trace(
                "claude-sonnet-4-6", "extract",
                input_tokens=1_000_000, output_tokens=1_000_000
            ),
        ]
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = traces
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_api_key = MagicMock()
        response = await get_llm_metrics(hours=24, db=mock_db, api_key=mock_api_key)
        assert response.total_cost_usd > 0

    @pytest.mark.asyncio
    async def test_single_trace_total_calls(self):
        from app.api.metrics import get_llm_metrics
        traces = [self._make_mock_trace()]
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = traces
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_api_key = MagicMock()
        response = await get_llm_metrics(hours=24, db=mock_db, api_key=mock_api_key)

        assert response.total_calls == 1
        assert len(response.by_model) == 1
        assert len(response.by_operation) == 1

    @pytest.mark.asyncio
    async def test_by_model_has_correct_fields(self):
        from app.api.metrics import get_llm_metrics
        traces = [self._make_mock_trace("claude-sonnet-4-6", "extract", "success", 500, 100, 50, 0.9)]
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = traces
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_api_key = MagicMock()
        response = await get_llm_metrics(hours=24, db=mock_db, api_key=mock_api_key)

        model_stat = response.by_model[0]
        assert model_stat.model == "claude-sonnet-4-6"
        assert model_stat.call_count == 1
        assert model_stat.input_tokens == 100
        assert model_stat.output_tokens == 50
