"""LangSmith tracing integration for the RAG pipeline.

Feature-flagged behind LANGSMITH_ENABLED=true. When disabled all functions
are no-ops so existing code and tests are unaffected.

Traces three RAG pipeline steps:
    embed       — input text -> embedding vector (Gemini)
    retrieve    — query vector -> retrieved chunks + relevance scores
    llm_call    — prompt -> LLM response (Claude)

Each run logs: operation, model, latency_ms, token usage, retrieval scores.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from app.config import settings

if TYPE_CHECKING:
    from app.services.llm_tracer import TraceContext

logger = logging.getLogger(__name__)

# Module-level state — populated by setup_langsmith()
_client: Any = None
_project: str = "docextract"


def setup_langsmith() -> None:
    """Configure LangSmith client and set environment variables.

    Safe to call when disabled — becomes a no-op. Import errors from missing
    packages are caught and logged so the app still starts without LangSmith.
    """
    global _client, _project

    if not settings.langsmith_enabled:
        return

    if not settings.langsmith_api_key:
        logger.warning(
            "LANGSMITH_ENABLED=true but LANGSMITH_API_KEY is not set — tracing skipped"
        )
        return

    try:
        from langsmith import Client  # type: ignore[import-untyped]
    except ImportError as e:
        logger.warning("langsmith package not installed, skipping LangSmith tracing: %s", e)
        return

    # Set env vars that the LangSmith SDK reads
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_API_KEY", settings.langsmith_api_key)
    os.environ.setdefault("LANGCHAIN_PROJECT", settings.langsmith_project)

    try:
        _client = Client(api_key=settings.langsmith_api_key)
        _project = settings.langsmith_project
        logger.info(
            "LangSmith tracing enabled — project '%s'",
            _project,
        )
    except Exception as exc:
        logger.warning("LangSmith client init failed: %s", exc)
        _client = None


def emit_rag_trace(ctx: "TraceContext", *, retrieval_scores: list[float] | None = None) -> None:
    """Post a completed RAG step to LangSmith as a Run.

    No-op when LangSmith is disabled or the client is not initialized.
    Called from llm_tracer.trace_llm_call in the finally block.

    Args:
        ctx: Completed TraceContext with timing/token data.
        retrieval_scores: Optional relevance scores from the retrieval step.
    """
    if not settings.langsmith_enabled or _client is None:
        return

    try:
        import uuid
        from datetime import datetime, timezone

        run_type = _operation_to_run_type(ctx.operation)
        now = datetime.now(timezone.utc)
        run_id = str(uuid.uuid4())

        inputs: dict[str, Any] = {
            "model": ctx.model,
            "operation": ctx.operation,
        }
        if ctx.prompt_hash is not None:
            inputs["prompt_hash"] = ctx.prompt_hash

        outputs: dict[str, Any] = {
            "status": ctx._status,
            "latency_ms": ctx.latency_ms,
        }
        if ctx._input_tokens is not None:
            outputs["input_tokens"] = ctx._input_tokens
        if ctx._output_tokens is not None:
            outputs["output_tokens"] = ctx._output_tokens
        if ctx._confidence is not None:
            outputs["confidence"] = ctx._confidence
        if retrieval_scores is not None:
            outputs["retrieval_scores"] = retrieval_scores
            if retrieval_scores:
                outputs["mean_retrieval_score"] = sum(retrieval_scores) / len(retrieval_scores)
        if ctx._error_message is not None:
            outputs["error"] = ctx._error_message

        _client.create_run(
            id=run_id,
            name=f"docextract.{ctx.operation}",
            run_type=run_type,
            project_name=_project,
            inputs=inputs,
            outputs=outputs,
            start_time=now,
            end_time=now,
            extra={"metadata": {"latency_ms": ctx.latency_ms}},
        )
    except Exception as exc:
        # Tracing must never break the main flow
        logger.debug("LangSmith emit_rag_trace failed silently: %s", exc)


def _operation_to_run_type(operation: str) -> str:
    """Map a DocExtract operation name to a LangSmith run type string."""
    _map = {
        "embed": "embedding",
        "retrieve": "retriever",
        "extract": "llm",
        "correct": "llm",
        "classify": "llm",
    }
    return _map.get(operation, "chain")


def _reset_for_testing() -> None:
    """Reset module-level state between tests. Not for production use."""
    global _client, _project
    _client = None
    _project = "docextract"
