"""Tests for OpenTelemetry observability module."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI


def _make_ctx(
    model="claude-sonnet-4-6",
    operation="extract",
    status="success",
    latency_ms=1200,
    input_tokens=100,
    output_tokens=50,
) -> MagicMock:
    ctx = MagicMock()
    ctx.model = model
    ctx.operation = operation
    ctx._status = status
    ctx.latency_ms = latency_ms
    ctx._input_tokens = input_tokens
    ctx._output_tokens = output_tokens
    return ctx


class TestSetupTelemetryDisabled:
    @patch("app.observability.settings")
    def test_noop_when_disabled(self, mock_settings):
        """setup_telemetry does nothing when otel_enabled=False."""
        import app.observability as obs

        mock_settings.otel_enabled = False
        app = FastAPI()
        obs.setup_telemetry(app)
        route_paths = [r.path for r in app.routes]
        assert "/metrics" not in route_paths

    @patch("app.observability.settings")
    def test_emit_noop_when_disabled(self, mock_settings):
        """emit_llm_metrics is silent when otel_enabled=False."""
        import app.observability as obs

        mock_settings.otel_enabled = False
        ctx = _make_ctx()
        obs.emit_llm_metrics(ctx)  # Must not raise

    @patch("app.observability.settings")
    def test_emit_noop_when_instruments_empty(self, mock_settings):
        """emit_llm_metrics is silent when _instruments not set up."""
        import app.observability as obs

        mock_settings.otel_enabled = True
        obs._reset_for_testing()
        ctx = _make_ctx()
        obs.emit_llm_metrics(ctx)  # Must not raise


class TestSetupTelemetryEnabled:
    def test_metrics_route_added_when_enabled(self):
        """/metrics endpoint mounted when otel_enabled=True."""
        import app.observability as obs

        obs._reset_for_testing()
        with patch("app.observability.settings") as mock_settings:
            mock_settings.otel_enabled = True
            mock_settings.otel_service_name = "test-docextract"
            app = FastAPI()
            obs.setup_telemetry(app)

        route_paths = [r.path for r in app.routes]
        assert "/metrics" in route_paths

    def test_instruments_initialized_after_setup(self):
        """_instruments dict populated after setup_telemetry."""
        import app.observability as obs

        obs._reset_for_testing()
        with patch("app.observability.settings") as mock_settings:
            mock_settings.otel_enabled = True
            mock_settings.otel_service_name = "test-docextract"
            app = FastAPI()
            obs.setup_telemetry(app)

        assert obs._instruments, "Instruments should be non-empty after setup"
        assert "duration" in obs._instruments
        assert "calls" in obs._instruments
        assert "tokens" in obs._instruments


class TestEmitLlmMetrics:
    def _setup_mock_instruments(self):
        """Helper: inject mock instruments into the module."""
        import app.observability as obs

        mock_hist = MagicMock()
        mock_counter = MagicMock()
        mock_token_counter = MagicMock()
        obs._meter = MagicMock()
        obs._instruments = {
            "duration": mock_hist,
            "calls": mock_counter,
            "tokens": mock_token_counter,
        }
        return mock_hist, mock_counter, mock_token_counter

    @patch("app.observability.settings")
    def test_emit_records_duration(self, mock_settings):
        """emit_llm_metrics records latency to histogram."""
        import app.observability as obs

        mock_settings.otel_enabled = True
        mock_hist, mock_counter, mock_tokens = self._setup_mock_instruments()

        ctx = _make_ctx(latency_ms=1200)
        obs.emit_llm_metrics(ctx)

        mock_hist.record.assert_called_once_with(
            1200,
            attributes={"model": "claude-sonnet-4-6", "operation": "extract", "status": "success"},
        )

    @patch("app.observability.settings")
    def test_emit_increments_call_counter(self, mock_settings):
        """emit_llm_metrics increments call counter."""
        import app.observability as obs

        mock_settings.otel_enabled = True
        mock_hist, mock_counter, mock_tokens = self._setup_mock_instruments()

        ctx = _make_ctx()
        obs.emit_llm_metrics(ctx)

        mock_counter.add.assert_called_once_with(
            1,
            attributes={"model": "claude-sonnet-4-6", "operation": "extract", "status": "success"},
        )

    @patch("app.observability.settings")
    def test_emit_records_tokens(self, mock_settings):
        """emit_llm_metrics records both input and output tokens."""
        import app.observability as obs

        mock_settings.otel_enabled = True
        mock_hist, mock_counter, mock_tokens = self._setup_mock_instruments()

        ctx = _make_ctx(input_tokens=80, output_tokens=40)
        obs.emit_llm_metrics(ctx)

        calls = [c[1] for c in mock_tokens.add.call_args_list]
        directions = {c["attributes"]["direction"] for c in calls}
        assert "input" in directions
        assert "output" in directions

    @patch("app.observability.settings")
    def test_emit_skips_tokens_when_none(self, mock_settings):
        """Token counter not called when tokens are None."""
        import app.observability as obs

        mock_settings.otel_enabled = True
        mock_hist, mock_counter, mock_tokens = self._setup_mock_instruments()

        ctx = _make_ctx(input_tokens=None, output_tokens=None)
        obs.emit_llm_metrics(ctx)

        mock_tokens.add.assert_not_called()


class TestLlmTracerBridge:
    @pytest.mark.asyncio
    async def test_trace_llm_call_triggers_emit(self):
        """trace_llm_call calls emit_llm_metrics after each call."""
        from app.services.llm_tracer import clear_in_memory_traces, trace_llm_call

        clear_in_memory_traces()
        with patch("app.services.llm_tracer.emit_llm_metrics") as mock_emit:
            async with trace_llm_call(None, "claude-haiku", "classify"):
                pass

        mock_emit.assert_called_once()
        ctx_arg = mock_emit.call_args[0][0]
        assert ctx_arg.model == "claude-haiku"
        assert ctx_arg.operation == "classify"
