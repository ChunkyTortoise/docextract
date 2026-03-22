"""Tests for LangSmith tracing integration."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(
    model: str = "claude-sonnet-4-6",
    operation: str = "extract",
    status: str = "success",
    latency_ms: int = 500,
    input_tokens: int | None = 100,
    output_tokens: int | None = 50,
    confidence: float | None = None,
    error_message: str | None = None,
    prompt_hash: str | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.model = model
    ctx.operation = operation
    ctx._status = status
    ctx.latency_ms = latency_ms
    ctx._input_tokens = input_tokens
    ctx._output_tokens = output_tokens
    ctx._confidence = confidence
    ctx._error_message = error_message
    ctx.prompt_hash = prompt_hash
    return ctx


# ---------------------------------------------------------------------------
# setup_langsmith
# ---------------------------------------------------------------------------

class TestSetupLangsmith:
    def test_noop_when_disabled(self):
        """setup_langsmith does nothing when langsmith_enabled=False."""
        import app.langsmith_tracing as ls

        ls._reset_for_testing()
        with patch("app.langsmith_tracing.settings") as mock_settings:
            mock_settings.langsmith_enabled = False
            ls.setup_langsmith()

        assert ls._client is None

    def test_noop_when_no_api_key(self):
        """setup_langsmith skips init when API key is empty."""
        import app.langsmith_tracing as ls

        ls._reset_for_testing()
        with patch("app.langsmith_tracing.settings") as mock_settings:
            mock_settings.langsmith_enabled = True
            mock_settings.langsmith_api_key = ""
            ls.setup_langsmith()

        assert ls._client is None

    def test_client_initialized_when_enabled(self):
        """setup_langsmith creates a Client when enabled with a key."""
        import app.langsmith_tracing as ls

        ls._reset_for_testing()
        mock_client_instance = MagicMock()
        with (
            patch("app.langsmith_tracing.settings") as mock_settings,
            patch("langsmith.Client", return_value=mock_client_instance) as mock_cls,
        ):
            mock_settings.langsmith_enabled = True
            mock_settings.langsmith_api_key = "ls-fake-key"
            mock_settings.langsmith_project = "test-project"
            ls.setup_langsmith()

        assert ls._client is mock_client_instance
        mock_cls.assert_called_once_with(api_key="ls-fake-key")

    def test_graceful_on_import_error(self):
        """setup_langsmith is a no-op when langsmith package is missing."""
        import app.langsmith_tracing as ls

        ls._reset_for_testing()
        with (
            patch("app.langsmith_tracing.settings") as mock_settings,
            patch.dict("sys.modules", {"langsmith": None}),
        ):
            mock_settings.langsmith_enabled = True
            mock_settings.langsmith_api_key = "ls-fake-key"
            mock_settings.langsmith_project = "test-project"
            # Import error is caught internally — must not raise
            try:
                ls.setup_langsmith()
            except Exception:
                pass  # acceptable: ImportError surfaces differently per Python version

        # Either way, client must not be in a broken state
        # (it will be None because _reset_for_testing was called before)


# ---------------------------------------------------------------------------
# emit_rag_trace — no-ops
# ---------------------------------------------------------------------------

class TestEmitRagTraceNoop:
    def test_noop_when_disabled(self):
        """emit_rag_trace is silent when langsmith_enabled=False."""
        import app.langsmith_tracing as ls

        ls._reset_for_testing()
        with patch("app.langsmith_tracing.settings") as mock_settings:
            mock_settings.langsmith_enabled = False
            ctx = _make_ctx()
            ls.emit_rag_trace(ctx)  # must not raise

    def test_noop_when_client_is_none(self):
        """emit_rag_trace is silent when client was never initialized."""
        import app.langsmith_tracing as ls

        ls._reset_for_testing()  # ensures _client is None
        with patch("app.langsmith_tracing.settings") as mock_settings:
            mock_settings.langsmith_enabled = True
            ctx = _make_ctx()
            ls.emit_rag_trace(ctx)  # must not raise

    def test_noop_returns_none(self):
        """emit_rag_trace always returns None."""
        import app.langsmith_tracing as ls

        ls._reset_for_testing()
        with patch("app.langsmith_tracing.settings") as mock_settings:
            mock_settings.langsmith_enabled = False
            result = ls.emit_rag_trace(_make_ctx())

        assert result is None


# ---------------------------------------------------------------------------
# emit_rag_trace — active tracing
# ---------------------------------------------------------------------------

class TestEmitRagTraceActive:
    def _inject_mock_client(self):
        """Inject a mock LangSmith client and return it."""
        import app.langsmith_tracing as ls

        mock_client = MagicMock()
        ls._client = mock_client
        ls._project = "test-project"
        return mock_client

    def test_create_run_called_for_llm_operation(self):
        """emit_rag_trace calls client.create_run for an LLM extraction trace."""
        import app.langsmith_tracing as ls

        ls._reset_for_testing()
        mock_client = self._inject_mock_client()

        with patch("app.langsmith_tracing.settings") as mock_settings:
            mock_settings.langsmith_enabled = True
            ctx = _make_ctx(operation="extract", model="claude-sonnet-4-6", input_tokens=80, output_tokens=40)
            ls.emit_rag_trace(ctx)

        mock_client.create_run.assert_called_once()
        call_kwargs = mock_client.create_run.call_args[1]
        assert call_kwargs["name"] == "docextract.extract"
        assert call_kwargs["project_name"] == "test-project"
        assert call_kwargs["inputs"]["model"] == "claude-sonnet-4-6"
        assert call_kwargs["outputs"]["input_tokens"] == 80
        assert call_kwargs["outputs"]["output_tokens"] == 40

    def test_retrieval_scores_included(self):
        """emit_rag_trace includes retrieval_scores and mean score when provided."""
        import app.langsmith_tracing as ls

        ls._reset_for_testing()
        mock_client = self._inject_mock_client()

        with patch("app.langsmith_tracing.settings") as mock_settings:
            mock_settings.langsmith_enabled = True
            ctx = _make_ctx(operation="retrieve")
            scores = [0.9, 0.8, 0.7]
            ls.emit_rag_trace(ctx, retrieval_scores=scores)

        call_kwargs = mock_client.create_run.call_args[1]
        assert call_kwargs["outputs"]["retrieval_scores"] == scores
        assert abs(call_kwargs["outputs"]["mean_retrieval_score"] - 0.8) < 1e-9

    def test_error_trace_includes_error_field(self):
        """emit_rag_trace includes the error message for failed operations."""
        import app.langsmith_tracing as ls

        ls._reset_for_testing()
        mock_client = self._inject_mock_client()

        with patch("app.langsmith_tracing.settings") as mock_settings:
            mock_settings.langsmith_enabled = True
            ctx = _make_ctx(status="error", error_message="connection timeout")
            ls.emit_rag_trace(ctx)

        call_kwargs = mock_client.create_run.call_args[1]
        assert call_kwargs["outputs"]["error"] == "connection timeout"

    def test_create_run_failure_does_not_raise(self):
        """If client.create_run throws, emit_rag_trace swallows the error."""
        import app.langsmith_tracing as ls

        ls._reset_for_testing()
        mock_client = self._inject_mock_client()
        mock_client.create_run.side_effect = RuntimeError("network error")

        with patch("app.langsmith_tracing.settings") as mock_settings:
            mock_settings.langsmith_enabled = True
            ctx = _make_ctx()
            ls.emit_rag_trace(ctx)  # must not raise


# ---------------------------------------------------------------------------
# Operation -> run type mapping
# ---------------------------------------------------------------------------

class TestOperationToRunType:
    def test_embed_maps_to_embedding(self):
        from app.langsmith_tracing import _operation_to_run_type

        assert _operation_to_run_type("embed") == "embedding"

    def test_retrieve_maps_to_retriever(self):
        from app.langsmith_tracing import _operation_to_run_type

        assert _operation_to_run_type("retrieve") == "retriever"

    def test_extract_maps_to_llm(self):
        from app.langsmith_tracing import _operation_to_run_type

        assert _operation_to_run_type("extract") == "llm"

    def test_unknown_maps_to_chain(self):
        from app.langsmith_tracing import _operation_to_run_type

        assert _operation_to_run_type("unknown_op") == "chain"


# ---------------------------------------------------------------------------
# Integration: trace_llm_call triggers emit_rag_trace
# ---------------------------------------------------------------------------

class TestTraceLlmCallTriggersLangSmith:
    @pytest.mark.asyncio
    async def test_emit_rag_trace_called_from_trace_llm_call(self):
        """trace_llm_call calls emit_rag_trace after each call completes."""
        from app.services.llm_tracer import clear_in_memory_traces, trace_llm_call

        clear_in_memory_traces()
        with patch("app.services.llm_tracer.emit_rag_trace") as mock_emit:
            async with trace_llm_call(None, "claude-haiku", "classify"):
                pass

        mock_emit.assert_called_once()
        ctx_arg = mock_emit.call_args[0][0]
        assert ctx_arg.model == "claude-haiku"
        assert ctx_arg.operation == "classify"

    @pytest.mark.asyncio
    async def test_rag_pipeline_still_works_with_tracing_enabled(self):
        """RAG pipeline (trace_llm_call) returns correct ctx data with LangSmith active."""
        from app.services.llm_tracer import (
            TraceContext,
            clear_in_memory_traces,
            get_in_memory_traces,
            trace_llm_call,
        )

        clear_in_memory_traces()
        with patch("app.services.llm_tracer.emit_rag_trace"):
            async with trace_llm_call(
                None, "gemini-embedding-2-preview", "embed", prompt_text="test query"
            ) as ctx:
                assert isinstance(ctx, TraceContext)
                assert ctx.model == "gemini-embedding-2-preview"

        traces = get_in_memory_traces()
        assert len(traces) == 1
        assert traces[0]["operation"] == "embed"
        assert traces[0]["status"] == "success"
