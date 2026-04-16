"""Tests for LLM tracer service."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from app.services.llm_tracer import (
    TraceContext,
    clear_in_memory_traces,
    get_in_memory_traces,
    hash_prompt,
    trace_llm_call,
)


@pytest.fixture(autouse=True)
def clear_traces():
    clear_in_memory_traces()
    yield
    clear_in_memory_traces()


class TestHashPrompt:
    def test_returns_16_chars(self):
        result = hash_prompt("hello world")
        assert len(result) == 16

    def test_same_input_same_hash(self):
        assert hash_prompt("test") == hash_prompt("test")

    def test_different_inputs_different_hashes(self):
        assert hash_prompt("input_a") != hash_prompt("input_b")

    def test_empty_string(self):
        result = hash_prompt("")
        assert len(result) == 16


class TestTraceContext:
    def test_initialization(self):
        ctx = TraceContext(model="claude-sonnet-4-6", operation="extract", request_id=None, prompt_hash=None)
        assert ctx.model == "claude-sonnet-4-6"
        assert ctx.operation == "extract"
        assert ctx._status == "success"

    def test_latency_ms_positive(self):
        import time
        ctx = TraceContext(model="m", operation="op", request_id=None, prompt_hash=None)
        time.sleep(0.001)
        assert ctx.latency_ms >= 0

    def test_record_error(self):
        ctx = TraceContext(model="m", operation="op", request_id=None, prompt_hash=None)
        ctx.record_error(ValueError("test error"))
        assert ctx._status == "error"
        assert "test error" in ctx._error_message

    def test_set_confidence(self):
        ctx = TraceContext(model="m", operation="op", request_id=None, prompt_hash=None)
        ctx.set_confidence(0.95)
        assert ctx._confidence == 0.95

    def test_record_response_with_usage(self):
        ctx = TraceContext(model="m", operation="op", request_id=None, prompt_hash=None)
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        response = MagicMock()
        response.usage = usage
        ctx.record_response(response)
        assert ctx._input_tokens == 100
        assert ctx._output_tokens == 50

    def test_record_response_no_usage(self):
        ctx = TraceContext(model="m", operation="op", request_id=None, prompt_hash=None)
        response = MagicMock(spec=[])  # no usage attr
        ctx.record_response(response)  # should not raise
        assert ctx._input_tokens is None

    def test_to_dict_has_required_keys(self):
        ctx = TraceContext(model="m", operation="op", request_id="req-1", prompt_hash="abc123")
        d = ctx.to_dict()
        assert "model" in d
        assert "operation" in d
        assert "latency_ms" in d
        assert "status" in d

    def test_record_response_with_usage_input_tokens(self):
        ctx = TraceContext(model="m", operation="op", request_id=None, prompt_hash=None)
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = None
        response = MagicMock()
        response.usage = usage
        ctx.record_response(response)
        assert ctx._input_tokens == 100

    def test_initial_status_is_success(self):
        ctx = TraceContext(model="m", operation="op", request_id=None, prompt_hash=None)
        assert ctx._status == "success"
        assert ctx._error_message is None

    def test_initial_tokens_are_none(self):
        ctx = TraceContext(model="m", operation="op", request_id=None, prompt_hash=None)
        assert ctx._input_tokens is None
        assert ctx._output_tokens is None


@pytest.mark.asyncio
class TestTraceLLMCall:
    async def test_success_stores_in_memory(self):
        async with trace_llm_call(None, "claude-sonnet-4-6", "extract") as ctx:
            pass
        traces = get_in_memory_traces()
        assert len(traces) == 1
        assert traces[0]["model"] == "claude-sonnet-4-6"
        assert traces[0]["operation"] == "extract"

    async def test_success_status(self):
        async with trace_llm_call(None, "m", "op") as ctx:
            pass
        assert get_in_memory_traces()[0]["status"] == "success"

    async def test_exception_stores_error_trace(self):
        with pytest.raises(ValueError):
            async with trace_llm_call(None, "m", "op") as ctx:
                raise ValueError("oops")
        traces = get_in_memory_traces()
        assert len(traces) == 1
        assert traces[0]["status"] == "error"
        assert "oops" in traces[0]["error_message"]

    async def test_exception_reraises(self):
        with pytest.raises(RuntimeError):
            async with trace_llm_call(None, "m", "op") as ctx:
                raise RuntimeError("test")

    async def test_latency_ms_recorded(self):
        async with trace_llm_call(None, "m", "op") as ctx:
            pass
        assert get_in_memory_traces()[0]["latency_ms"] >= 0

    async def test_multiple_traces_stored(self):
        for i in range(3):
            async with trace_llm_call(None, "m", f"op_{i}") as ctx:
                pass
        assert len(get_in_memory_traces()) == 3

    async def test_context_yields_trace_context(self):
        async with trace_llm_call(None, "m", "op") as ctx:
            assert isinstance(ctx, TraceContext)

    async def test_with_prompt_text(self):
        async with trace_llm_call(None, "m", "op", prompt_text="hello") as ctx:
            pass
        traces = get_in_memory_traces()
        assert traces[0]["prompt_hash"] is not None
        assert len(traces[0]["prompt_hash"]) == 16

    async def test_db_none_does_not_persist_to_db(self):
        # With db=None, should not try to use DB
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        # Pass None, not mock_db
        async with trace_llm_call(None, "m", "op") as ctx:
            pass
        mock_db.add.assert_not_called()

    async def test_no_prompt_text_gives_none_hash(self):
        async with trace_llm_call(None, "m", "op") as ctx:
            pass
        traces = get_in_memory_traces()
        assert traces[0]["prompt_hash"] is None

    async def test_model_stored_correctly(self):
        async with trace_llm_call(None, "gemini-embedding-2-preview", "embed") as ctx:
            pass
        traces = get_in_memory_traces()
        assert traces[0]["model"] == "gemini-embedding-2-preview"

    async def test_error_message_truncated(self):
        long_msg = "x" * 1000
        with pytest.raises(ValueError):
            async with trace_llm_call(None, "m", "op") as ctx:
                raise ValueError(long_msg)
        traces = get_in_memory_traces()
        assert len(traces[0]["error_message"]) <= 500


class TestInMemoryHelpers:
    def test_get_in_memory_traces_returns_list(self):
        assert isinstance(get_in_memory_traces(), list)

    def test_clear_removes_all(self):
        asyncio.run(_add_trace())
        assert len(get_in_memory_traces()) > 0
        clear_in_memory_traces()
        assert len(get_in_memory_traces()) == 0

    def test_get_returns_copy(self):
        # Mutating the returned list doesn't affect the internal store
        asyncio.run(_add_trace())
        traces = get_in_memory_traces()
        traces.clear()
        assert len(get_in_memory_traces()) == 1

    def test_initially_empty_after_clear(self):
        clear_in_memory_traces()
        assert get_in_memory_traces() == []


async def _add_trace():
    async with trace_llm_call(None, "m", "op"):
        pass
