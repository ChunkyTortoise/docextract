"""LLM call tracer for observability. Dual-mode: DB or in-memory."""
from __future__ import annotations

import hashlib
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

# In-memory store for test/eval mode
_in_memory_traces: list[dict] = []


@dataclass
class TraceContext:
    """Holds mutable state during a traced LLM call."""
    model: str
    operation: str
    request_id: str | None
    prompt_hash: str | None
    _start_time: float = field(default_factory=time.monotonic, init=False)
    _input_tokens: int | None = None
    _output_tokens: int | None = None
    _confidence: float | None = None
    _retries: int = 0
    _status: str = "success"
    _error_message: str | None = None

    def record_response(self, response: Any) -> None:
        """Extract token counts from Anthropic/Gemini response."""
        try:
            usage = getattr(response, "usage", None)
            if usage:
                self._input_tokens = getattr(usage, "input_tokens", None)
                self._output_tokens = getattr(usage, "output_tokens", None)
        except Exception:
            pass

    def record_error(self, e: Exception) -> None:
        """Record an error."""
        self._status = "error"
        self._error_message = str(e)[:500]

    def set_confidence(self, confidence: float) -> None:
        """Set extraction confidence."""
        self._confidence = confidence

    @property
    def latency_ms(self) -> int:
        return int((time.monotonic() - self._start_time) * 1000)

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "operation": self.operation,
            "request_id": self.request_id,
            "prompt_hash": self.prompt_hash,
            "input_tokens": self._input_tokens,
            "output_tokens": self._output_tokens,
            "latency_ms": self.latency_ms,
            "confidence": self._confidence,
            "retries": self._retries,
            "status": self._status,
            "error_message": self._error_message,
        }


@asynccontextmanager
async def trace_llm_call(
    db: "AsyncSession | None",
    model: str,
    operation: str,
    request_id: str | None = None,
    prompt_text: str | None = None,
):
    """Async context manager that times and records an LLM call.

    Usage:
        async with trace_llm_call(db, "claude-sonnet-4-6", "extract") as ctx:
            response = await client.messages.create(...)
            ctx.record_response(response)

    If db is None, stores trace in-memory (for tests/eval).
    """
    prompt_hash = hash_prompt(prompt_text) if prompt_text else None
    ctx = TraceContext(
        model=model,
        operation=operation,
        request_id=request_id,
        prompt_hash=prompt_hash,
    )

    try:
        yield ctx
    except Exception as e:
        ctx.record_error(e)
        raise
    finally:
        trace_data = ctx.to_dict()
        if db is not None:
            await _persist_trace(db, trace_data)
        else:
            _in_memory_traces.append(trace_data)


async def _persist_trace(db: "AsyncSession", data: dict) -> None:
    """Persist a trace to the database."""
    import uuid
    from app.models.llm_trace import LLMTrace

    try:
        trace = LLMTrace(
            id=str(uuid.uuid4()),
            trace_id=data.get("request_id"),
            request_id=data.get("request_id"),
            model=data["model"],
            operation=data["operation"],
            input_tokens=data.get("input_tokens"),
            output_tokens=data.get("output_tokens"),
            latency_ms=data.get("latency_ms"),
            confidence=data.get("confidence"),
            retries=data.get("retries", 0),
            prompt_hash=data.get("prompt_hash"),
            status=data.get("status", "success"),
            error_message=data.get("error_message"),
        )
        db.add(trace)
        await db.flush()
    except Exception:
        pass  # Tracing must never break the main flow


def hash_prompt(text: str) -> str:
    """MD5 hash of prompt text, first 16 chars for change detection."""
    return hashlib.md5(text.encode()).hexdigest()[:16]


def get_in_memory_traces() -> list[dict]:
    """Get all in-memory traces (for testing)."""
    return list(_in_memory_traces)


def clear_in_memory_traces() -> None:
    """Clear in-memory traces (for testing)."""
    _in_memory_traces.clear()
