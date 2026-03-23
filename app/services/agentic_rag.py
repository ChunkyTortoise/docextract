"""Agentic RAG with ReAct reasoning loop.

Think → Act → Observe, repeated until confident or max_iterations reached.
"""
from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel

from app.services.rag_tools import RagTools, SearchResult

if TYPE_CHECKING:
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


class AgenticRAGResult(BaseModel):
    answer: str
    sources: list[SearchResult]
    reasoning_trace: list[ReasoningStep]
    iterations: int
    confidence: float
    tools_used: list[str]
    question: str


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

    def __init__(self, tools: RagTools, model_router: "ModelRouter") -> None:
        self._tools = tools
        self._router = model_router

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self,
        question: str,
        doc_ids: list[str] | None = None,
        max_iterations: int = 3,
    ) -> AgenticRAGResult:
        """Run the ReAct loop and return a fully-traced result."""
        from app.config import settings

        accumulated_results: list[SearchResult] = []
        reasoning_trace: list[ReasoningStep] = []
        tools_used: list[str] = []
        final_answer = ""
        final_confidence = 0.0

        for iteration in range(1, max_iterations + 1):
            # ---- THINK: which tool to call? ----
            think_response = await self._call_llm(
                system=_THINK_SYSTEM,
                user=self._build_think_prompt(question, accumulated_results, doc_ids),
                models=settings.classification_models,
                operation="rag_think",
            )
            think_data = _parse_json(think_response)
            thought = str(think_data.get("thought", ""))
            action = str(think_data.get("action", "search_hybrid"))
            action_input: dict = dict(think_data.get("action_input", {}))

            # Ensure doc_ids filter is forwarded if specified at request level
            if doc_ids and "doc_ids" not in action_input:
                action_input["doc_ids"] = doc_ids

            # ---- ACT: execute the tool ----
            tool_results, observation = await self._execute_tool(action, action_input)

            if tool_results:
                accumulated_results = _merge_results(accumulated_results, tool_results)
            if action not in tools_used:
                tools_used.append(action)

            # ---- OBSERVE: self-assess confidence ----
            evaluate_response = await self._call_llm(
                system=_EVALUATE_SYSTEM,
                user=self._build_evaluate_prompt(question, accumulated_results),
                models=settings.classification_models,
                operation="rag_evaluate",
            )
            eval_data = _parse_json(evaluate_response)
            confidence = float(eval_data.get("confidence", 0.0))
            reasoning = str(eval_data.get("reasoning", ""))
            candidate_answer = str(eval_data.get("final_answer", ""))

            reasoning_trace.append(
                ReasoningStep(
                    step=iteration,
                    thought=thought,
                    action=action,
                    action_input=action_input,
                    observation=observation,
                    confidence=confidence,
                )
            )

            final_confidence = confidence

            if confidence >= CONFIDENCE_THRESHOLD or iteration == max_iterations:
                if candidate_answer:
                    final_answer = candidate_answer
                else:
                    # Generate final answer explicitly
                    final_answer = await self._generate_answer(
                        question, accumulated_results, models=settings.extraction_models
                    )
                break

        # Deduplicate sources
        sources = _deduplicate(accumulated_results)[:10]

        return AgenticRAGResult(
            answer=final_answer or "No relevant information found.",
            sources=sources,
            reasoning_trace=reasoning_trace,
            iterations=len(reasoning_trace),
            confidence=final_confidence,
            tools_used=tools_used,
            question=question,
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
    ) -> str:
        """Route an LLM call through ModelRouter for fallback support."""
        from anthropic import AsyncAnthropic
        from app.config import settings

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)

        async def _call(model: str) -> str:
            response = await client.messages.create(
                model=model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
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

    async def _execute_tool(
        self,
        action: str,
        action_input: dict,
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
                # Rerank happens on existing accumulated results — caller should pass them
                # For the agent loop we skip this as a standalone action (no-op here)
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

def _parse_json(text: str) -> dict:
    """Extract the first JSON object from a string."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


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
