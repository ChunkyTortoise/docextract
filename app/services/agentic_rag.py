"""Agentic RAG with ReAct reasoning loop.

Think → Act → Observe, repeated until confident or max_iterations reached.
Supports both batch (search) and streaming (search_stream) execution.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from app.services.cost_tracker import CostTracker
from app.services.rag_tools import RagTools, SearchResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.model_router import ModelRouter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------

class ReasoningStep(BaseModel):
    step: int
    thought: str
    action: str
    action_input: dict
    observation: str
    confidence: float
    parse_failed: bool = False


class AgenticRAGResult(BaseModel):
    answer: str
    sources: list[SearchResult]
    reasoning_trace: list[ReasoningStep]
    iterations: int
    confidence: float
    tools_used: list[str]
    question: str
    degraded: bool = False
    degradation_reason: str | None = None


class StreamEvent(BaseModel):
    """Event emitted during streaming agent search."""
    event_type: Literal["step", "done"]
    step: ReasoningStep | None = None
    result: AgenticRAGResult | None = None


# ---------------------------------------------------------------------------
# Internal iteration state
# ---------------------------------------------------------------------------

@dataclass
class _IterationState:
    """Mutable state carried between ReAct iterations."""
    accumulated_results: list[SearchResult] = field(default_factory=list)
    reasoning_trace: list[ReasoningStep] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    final_answer: str = ""
    final_confidence: float = 0.0
    should_stop: bool = False
    accumulated_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    degraded: bool = False
    degradation_reason: str | None = None


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_THINK_SYSTEM = (
    "You are a document retrieval agent. "
    "Decide which search tool to call next to answer the user's question. "
    "Available tools: search_vectors, search_bm25, search_hybrid, lookup_metadata, rerank_results. "
    "Respond ONLY with a JSON object with keys: thought (string), action (tool name), "
    "action_input (object with 'query' and optionally 'top_k', 'doc_ids', 'alpha')."
)

_EVALUATE_SYSTEM = (
    "You are a relevance assessor. "
    "Given a question and retrieved passages, decide if you have enough information to answer confidently. "
    "Respond ONLY with a JSON object with keys: "
    "confidence (float 0-1), reasoning (string), "
    "final_answer (string if confidence >= 0.8, else empty string)."
)

_ANSWER_SYSTEM = (
    "You are a precise document QA assistant. "
    "Answer the question using ONLY the provided context. "
    "Be concise, factual, and cite relevant passages."
)

CONFIDENCE_THRESHOLD = 0.8


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class AgenticRAG:
    """ReAct agent loop that orchestrates RagTools to answer questions."""

    def __init__(self, tools: RagTools, model_router: ModelRouter) -> None:
        self._tools = tools
        self._router = model_router
        self._cost_tracker = CostTracker()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self,
        question: str,
        doc_ids: list[str] | None = None,
        max_iterations: int = 3,
        db: AsyncSession | None = None,
    ) -> AgenticRAGResult:
        """Run the ReAct loop and return a fully-traced result."""
        state = _IterationState()

        for iteration in range(1, max_iterations + 1):
            reason = await self._check_spend_ceiling(state, db)
            if reason:
                self._apply_degradation(state, reason)
                break
            await self._run_iteration(
                iteration=iteration,
                max_iterations=max_iterations,
                question=question,
                doc_ids=doc_ids,
                state=state,
                db=db,
            )
            if state.should_stop:
                break

        return self._build_result(question, state)

    async def search_stream(
        self,
        question: str,
        doc_ids: list[str] | None = None,
        max_iterations: int = 3,
        db: AsyncSession | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream ReAct reasoning steps as they execute.

        Yields a StreamEvent with event_type="step" after each Think/Act/Observe
        cycle, then a final StreamEvent with event_type="done" containing the
        complete AgenticRAGResult.
        """
        state = _IterationState()

        for iteration in range(1, max_iterations + 1):
            reason = await self._check_spend_ceiling(state, db)
            if reason:
                self._apply_degradation(state, reason)
                break
            await self._run_iteration(
                iteration=iteration,
                max_iterations=max_iterations,
                question=question,
                doc_ids=doc_ids,
                state=state,
                db=db,
            )
            # Yield the step that was just appended
            yield StreamEvent(
                event_type="step",
                step=state.reasoning_trace[-1],
            )
            if state.should_stop:
                break

        result = self._build_result(question, state)
        yield StreamEvent(event_type="done", result=result)

    # ------------------------------------------------------------------
    # Iteration engine (shared by search and search_stream)
    # ------------------------------------------------------------------

    async def _run_iteration(
        self,
        iteration: int,
        max_iterations: int,
        question: str,
        doc_ids: list[str] | None,
        state: _IterationState,
        db: AsyncSession | None = None,
    ) -> None:
        """Execute one Think → Act → Observe cycle, mutating *state* in place."""
        from app.config import settings

        # ---- THINK: which tool to call? ----
        think_response = await self._call_llm(
            system=_THINK_SYSTEM,
            user=self._build_think_prompt(question, state.accumulated_results, doc_ids),
            models=settings.classification_models,
            operation="rag_think",
            state=state,
        )
        think_data = _parse_json(think_response)
        thought = str(think_data.get("thought", ""))
        action = str(think_data.get("action", "search_hybrid"))
        action_input: dict = dict(think_data.get("action_input", {}))

        if doc_ids and "doc_ids" not in action_input:
            action_input["doc_ids"] = doc_ids

        # ---- ACT: execute the tool ----
        tool_results, observation = await self._execute_tool(action, action_input, accumulated_results=state.accumulated_results)

        if tool_results:
            state.accumulated_results = _merge_results(state.accumulated_results, tool_results)
        if action not in state.tools_used:
            state.tools_used.append(action)

        # ---- Spend ceiling check between ACT and OBSERVE (THINK call may have
        # already pushed accumulated cost past the per-request ceiling) ----
        reason = await self._check_spend_ceiling(state, db)
        if reason:
            self._apply_degradation(state, reason)
            return

        # ---- OBSERVE: self-assess confidence ----
        evaluate_response = await self._call_llm(
            system=_EVALUATE_SYSTEM,
            user=self._build_evaluate_prompt(question, state.accumulated_results),
            models=settings.classification_models,
            operation="rag_evaluate",
            state=state,
        )
        eval_data, eval_parse_ok = _parse_json_safe(evaluate_response)
        if eval_parse_ok:
            confidence = float(eval_data.get("confidence", 0.0))
            candidate_answer = str(eval_data.get("final_answer", ""))
        else:
            confidence = 0.0
            candidate_answer = ""

        state.reasoning_trace.append(
            ReasoningStep(
                step=iteration,
                thought=thought,
                action=action,
                action_input=action_input,
                observation=observation,
                confidence=confidence,
                parse_failed=not eval_parse_ok,
            )
        )
        state.final_confidence = confidence

        has_results = bool(state.accumulated_results)
        if (confidence >= CONFIDENCE_THRESHOLD and has_results) or iteration == max_iterations:
            if not has_results:
                self._apply_degradation(state, "empty_retrieval")
            elif candidate_answer:
                state.final_answer = candidate_answer
            else:
                reason = await self._check_spend_ceiling(state, db)
                if reason:
                    self._apply_degradation(state, reason)
                else:
                    state.final_answer = await self._generate_answer(
                        question, state.accumulated_results, models=settings.extraction_models, state=state
                    )
            state.should_stop = True

    @staticmethod
    def _degraded_answer(state: _IterationState) -> str:
        """Best-effort answer to return when the loop stops early degraded."""
        if state.final_answer:
            return state.final_answer
        if state.accumulated_results:
            top = state.accumulated_results[0]
            return (
                "Spend ceiling reached before a confident answer could be generated. "
                f"Best-effort context: {top.content[:300]}"
            )
        if state.degradation_reason == "empty_retrieval":
            return "No relevant passages were retrieved; unable to produce a grounded answer."
        return "Spend ceiling reached before any relevant information could be retrieved."

    def _apply_degradation(self, state: _IterationState, reason: str) -> None:
        """Mark *state* as degraded and stop the loop gracefully (no raise)."""
        state.degraded = True
        state.degradation_reason = reason
        state.should_stop = True
        state.final_answer = self._degraded_answer(state)

    async def _check_spend_ceiling(
        self,
        state: _IterationState,
        db: AsyncSession | None,
    ) -> str | None:
        """Return a degradation reason if the configured spend ceiling would be
        exceeded by the next model call, else None. Inert unless
        settings.spend_ceiling_enabled is True.
        """
        from app.config import settings

        if not settings.spend_ceiling_enabled:
            return None

        per_request_ceiling = Decimal(str(settings.spend_ceiling_per_request_usd))
        if state.accumulated_cost_usd >= per_request_ceiling:
            return "per_request_ceiling_exceeded"

        if db is not None:
            per_day_ceiling = Decimal(str(settings.spend_ceiling_per_day_usd))
            summary = await self._cost_tracker.get_cost_summary(db, days=1)
            daily_total = sum(
                (
                    Decimal(str(op_data["total_cost"]))
                    for model_data in summary.values()
                    for op_data in model_data.values()
                ),
                Decimal("0"),
            )
            if daily_total >= per_day_ceiling:
                return "per_day_ceiling_exceeded"

        return None

    @staticmethod
    def _build_result(question: str, state: _IterationState) -> AgenticRAGResult:
        """Assemble the final result from accumulated iteration state."""
        sources = _deduplicate(state.accumulated_results)[:10]
        return AgenticRAGResult(
            answer=state.final_answer or "No relevant information found.",
            sources=sources,
            reasoning_trace=state.reasoning_trace,
            iterations=len(state.reasoning_trace),
            confidence=state.final_confidence,
            tools_used=state.tools_used,
            question=question,
            degraded=state.degraded,
            degradation_reason=state.degradation_reason,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        system: str,
        user: str,
        models: list[str],
        operation: str,
        state: _IterationState | None = None,
    ) -> str:
        """Route an LLM call through ModelRouter for fallback support."""
        from anthropic import AsyncAnthropic

        from app.config import settings

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)

        async def _call(model: str) -> str:
            start = time.monotonic()
            response = await client.messages.create(
                model=model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            if state is not None and settings.spend_ceiling_enabled:
                self._record_cost(state, model, response, operation, (time.monotonic() - start) * 1000)
            return response.content[0].text

        try:
            result, _ = await self._router.call_with_fallback(
                operation=operation,
                chain=models,
                call_fn=_call,
            )
            return result
        except Exception as exc:
            logger.warning("LLM call failed for operation=%s: %s", operation, exc)
            return "{}"

    def _record_cost(
        self,
        state: _IterationState,
        model: str,
        response: object,
        operation: str,
        latency_ms: float,
    ) -> None:
        """Accumulate the estimated USD cost of one model call onto *state*.

        Silently skips models absent from CostTracker's pricing table (e.g.
        third-party fallback models with no known per-token rate) rather than
        failing the request.
        """
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        try:
            cost = self._cost_tracker.compute_cost(
                model=model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                operation=operation,
                latency_ms=latency_ms,
            )
        except ValueError:
            logger.debug("No pricing data for model=%s; skipping cost accounting", model)
            return
        state.accumulated_cost_usd += cost.total_cost_usd

    async def _execute_tool(
        self,
        action: str,
        action_input: dict,
        accumulated_results: list[SearchResult] | None = None,
    ) -> tuple[list[SearchResult], str]:
        """Execute a named tool and return (results, observation_summary)."""
        query = str(action_input.get("query", ""))
        top_k = int(action_input.get("top_k", 5))
        doc_ids: list[str] | None = action_input.get("doc_ids")
        alpha = float(action_input.get("alpha", 0.5))

        try:
            if action == "search_vectors":
                results = await self._tools.search_vectors(query=query, top_k=top_k, doc_ids=doc_ids)
            elif action == "search_bm25":
                results = await self._tools.search_bm25(query=query, top_k=top_k, doc_ids=doc_ids)
            elif action == "search_hybrid":
                results = await self._tools.search_hybrid(query=query, top_k=top_k, alpha=alpha)
            elif action == "lookup_metadata":
                doc_id = str(action_input.get("doc_id", query))
                meta = await self._tools.lookup_metadata(doc_id)
                observation = f"Metadata for {doc_id}: {json.dumps(meta)}"
                return [], observation
            elif action == "rerank_results":
                # Rerank accumulated results using TF-IDF cross-score
                if accumulated_results:
                    from app.services.reranker import TFIDFReranker
                    reranker = TFIDFReranker(alpha=float(action_input.get("alpha", 0.4)))
                    results = reranker.rerank(
                        query=query,
                        results=list(accumulated_results),
                        top_k=top_k,
                    )
                    observation = (
                        f"Reranked {len(results)} results by TF-IDF cross-score. "
                        + (f"Top result score: {results[0].score:.3f}" if results else "No results.")
                    )
                    return results, observation
                else:
                    results = []
            else:
                logger.warning("Unknown tool action: %s", action)
                results = []

            observation = (
                f"Tool '{action}' returned {len(results)} result(s). "
                + (f"Top result: {results[0].content[:200]}" if results else "No results found.")
            )
            return results, observation

        except Exception as exc:
            logger.warning("Tool execution failed action=%s: %s", action, exc)
            return [], f"Tool '{action}' failed: {exc}"

    async def _generate_answer(
        self,
        question: str,
        results: list[SearchResult],
        models: list[str],
        state: _IterationState | None = None,
    ) -> str:
        """Generate a final answer given question + context passages."""
        context = "\n\n".join(
            f"[{i + 1}] {r.content[:500]}" for i, r in enumerate(results[:5])
        )
        user_prompt = (
            f"Context passages:\n{context}\n\n"
            f"Question: {question}\n\n"
            "Answer concisely using only the context above."
        )
        return await self._call_llm(
            system=_ANSWER_SYSTEM,
            user=user_prompt,
            models=models,
            operation="rag_answer",
            state=state,
        )

    @staticmethod
    def _build_think_prompt(
        question: str,
        so_far: list[SearchResult],
        doc_ids: list[str] | None,
    ) -> str:
        prior = (
            f"Results collected so far ({len(so_far)} passages):\n"
            + "\n".join(f"  - {r.content[:150]}" for r in so_far[:3])
            if so_far
            else "No results collected yet."
        )
        filter_note = f"Restrict search to doc_ids: {doc_ids}" if doc_ids else ""
        return (
            f"Question: {question}\n\n"
            f"{prior}\n\n"
            f"{filter_note}\n\n"
            "Which tool should I call next? Respond with JSON."
        )

    @staticmethod
    def _build_evaluate_prompt(
        question: str,
        results: list[SearchResult],
    ) -> str:
        context = "\n\n".join(
            f"[{i + 1}] (score={r.score:.3f}) {r.content[:400]}"
            for i, r in enumerate(results[:5])
        )
        return (
            f"Question: {question}\n\n"
            f"Retrieved passages:\n{context or 'None'}\n\n"
            "Do I have enough information to answer confidently? Respond with JSON."
        )


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _parse_json_safe(text: str) -> tuple[dict, bool]:
    """Extract the first JSON object from a string.

    Returns (data, ok) where ok is False if no valid JSON object could be
    parsed, so callers can distinguish a genuine parse failure from a
    legitimately empty response.
    """
    text = text.strip()
    try:
        return json.loads(text), True
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0)), True
        except json.JSONDecodeError:
            pass
    return {}, False


def _parse_json(text: str) -> dict:
    """Extract the first JSON object from a string."""
    data, _ = _parse_json_safe(text)
    return data


def _merge_results(
    existing: list[SearchResult],
    new: list[SearchResult],
) -> list[SearchResult]:
    """Merge new results into existing, deduplicating by chunk_id/doc_id."""
    seen = {(r.chunk_id or r.doc_id) for r in existing}
    merged = list(existing)
    for r in new:
        key = r.chunk_id or r.doc_id
        if key not in seen:
            merged.append(r)
            seen.add(key)
    return sorted(merged, key=lambda x: x.score, reverse=True)


def _deduplicate(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    out: list[SearchResult] = []
    for r in results:
        key = r.chunk_id or r.doc_id
        if key not in seen:
            out.append(r)
            seen.add(key)
    return out
