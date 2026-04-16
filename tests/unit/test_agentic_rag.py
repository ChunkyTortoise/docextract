"""Unit tests for AgenticRAG ReAct loop — all Claude calls mocked."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.agentic_rag import AgenticRAG, AgenticRAGResult, ReasoningStep
from app.services.rag_tools import RagTools, SearchResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _search_result(doc_id="d1", chunk_id="c1", content="sample content", score=0.9) -> SearchResult:
    return SearchResult(doc_id=doc_id, chunk_id=chunk_id, content=content, score=score)


def _make_tools(search_results: list[SearchResult] | None = None) -> RagTools:
    """Return a RagTools with all search methods mocked."""
    tools = MagicMock(spec=RagTools)
    results = search_results or [_search_result()]
    tools.search_vectors = AsyncMock(return_value=results)
    tools.search_bm25 = AsyncMock(return_value=results)
    tools.search_hybrid = AsyncMock(return_value=results)
    tools.lookup_metadata = AsyncMock(return_value={"doc_id": "d1", "document_type": "invoice"})
    tools.rerank_results = AsyncMock(side_effect=lambda q, r: r)
    return tools


def _make_router(responses: list[str]) -> MagicMock:
    """Return a ModelRouter mock whose call_with_fallback cycles through responses."""
    router = MagicMock()
    call_count = 0

    async def _call_with_fallback(operation, chain, call_fn):
        nonlocal call_count
        resp = responses[min(call_count, len(responses) - 1)]
        call_count += 1
        return resp, chain[0] if chain else "mock-model"

    router.call_with_fallback = _call_with_fallback
    return router


def _think_json(action: str = "search_hybrid", query: str = "test") -> str:
    return json.dumps({
        "thought": "I should search for relevant documents.",
        "action": action,
        "action_input": {"query": query},
    })


def _evaluate_json(confidence: float = 0.9, answer: str = "The answer is X.") -> str:
    return json.dumps({
        "confidence": confidence,
        "reasoning": "Sufficient passages retrieved.",
        "final_answer": answer if confidence >= 0.8 else "",
    })


# ---------------------------------------------------------------------------
# Single iteration (high confidence immediately)
# ---------------------------------------------------------------------------

class TestAgenticRAGSingleIteration:
    @pytest.mark.asyncio
    async def test_single_iteration_high_confidence(self):
        tools = _make_tools()
        # think → evaluate (high confidence)
        router = _make_router([_think_json(), _evaluate_json(confidence=0.95, answer="Found it.")])
        agent = AgenticRAG(tools=tools, model_router=router)

        result = await agent.search("What is the invoice total?", max_iterations=3)

        assert isinstance(result, AgenticRAGResult)
        assert result.iterations == 1
        assert result.confidence >= 0.8
        assert result.answer == "Found it."
        assert "search_hybrid" in result.tools_used

    @pytest.mark.asyncio
    async def test_returns_agenticragresult_type(self):
        tools = _make_tools()
        router = _make_router([_think_json(), _evaluate_json(confidence=0.9, answer="Yes.")])
        agent = AgenticRAG(tools=tools, model_router=router)

        result = await agent.search("test question")

        assert isinstance(result, AgenticRAGResult)
        assert isinstance(result.sources, list)
        assert isinstance(result.reasoning_trace, list)
        assert isinstance(result.tools_used, list)

    @pytest.mark.asyncio
    async def test_question_preserved_in_result(self):
        tools = _make_tools()
        router = _make_router([_think_json(), _evaluate_json(confidence=0.9, answer="A.")])
        agent = AgenticRAG(tools=tools, model_router=router)

        result = await agent.search("What is the vendor name?")

        assert result.question == "What is the vendor name?"


# ---------------------------------------------------------------------------
# Multi-iteration (low confidence → retry)
# ---------------------------------------------------------------------------

class TestAgenticRAGMultiIteration:
    @pytest.mark.asyncio
    async def test_low_confidence_triggers_second_iteration(self):
        tools = _make_tools()
        # iteration 1: low confidence; iteration 2: high confidence
        responses = [
            _think_json("search_vectors"),
            _evaluate_json(confidence=0.4),   # not confident yet
            _think_json("search_bm25"),
            _evaluate_json(confidence=0.9, answer="Found after retry."),
        ]
        router = _make_router(responses)
        agent = AgenticRAG(tools=tools, model_router=router)

        result = await agent.search("vendor name?", max_iterations=3)

        assert result.iterations == 2
        assert result.confidence == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_reasoning_trace_captures_each_step(self):
        tools = _make_tools()
        responses = [
            _think_json("search_vectors"),
            _evaluate_json(confidence=0.3),
            _think_json("search_bm25"),
            _evaluate_json(confidence=0.9, answer="Done."),
        ]
        router = _make_router(responses)
        agent = AgenticRAG(tools=tools, model_router=router)

        result = await agent.search("question?", max_iterations=3)

        assert len(result.reasoning_trace) == 2
        for step in result.reasoning_trace:
            assert isinstance(step, ReasoningStep)
            assert isinstance(step.thought, str)
            assert isinstance(step.action, str)
            assert isinstance(step.observation, str)
            assert 0.0 <= step.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_tools_used_list_is_populated(self):
        tools = _make_tools()
        responses = [
            _think_json("search_vectors"),
            _evaluate_json(confidence=0.3),
            _think_json("search_bm25"),
            _evaluate_json(confidence=0.9, answer="Done."),
        ]
        router = _make_router(responses)
        agent = AgenticRAG(tools=tools, model_router=router)

        result = await agent.search("anything?", max_iterations=3)

        assert "search_vectors" in result.tools_used
        assert "search_bm25" in result.tools_used

    @pytest.mark.asyncio
    async def test_tools_used_deduplicates(self):
        """Same tool called twice should appear once in tools_used."""
        tools = _make_tools()
        responses = [
            _think_json("search_hybrid"),
            _evaluate_json(confidence=0.3),
            _think_json("search_hybrid"),   # same tool again
            _evaluate_json(confidence=0.9, answer="Done."),
        ]
        router = _make_router(responses)
        agent = AgenticRAG(tools=tools, model_router=router)

        result = await agent.search("anything?", max_iterations=3)

        assert result.tools_used.count("search_hybrid") == 1


# ---------------------------------------------------------------------------
# max_iterations stops the loop
# ---------------------------------------------------------------------------

class TestAgenticRAGMaxIterations:
    @pytest.mark.asyncio
    async def test_max_iterations_stops_loop(self):
        tools = _make_tools()
        # Always low confidence — should stop at max_iterations=2
        responses = [
            _think_json(), _evaluate_json(confidence=0.2),
            _think_json(), _evaluate_json(confidence=0.2),
            _think_json(), _evaluate_json(confidence=0.2),
        ]
        router = _make_router(responses)
        agent = AgenticRAG(tools=tools, model_router=router)

        result = await agent.search("question?", max_iterations=2)

        assert result.iterations == 2
        # Should still return a result (not raise)
        assert isinstance(result, AgenticRAGResult)

    @pytest.mark.asyncio
    async def test_max_iterations_one_always_returns(self):
        tools = _make_tools()
        router = _make_router([_think_json(), _evaluate_json(confidence=0.1)])
        agent = AgenticRAG(tools=tools, model_router=router)

        result = await agent.search("q?", max_iterations=1)

        assert result.iterations == 1
        assert isinstance(result.answer, str)


# ---------------------------------------------------------------------------
# Empty results path
# ---------------------------------------------------------------------------

class TestAgenticRAGEmptyResults:
    @pytest.mark.asyncio
    async def test_empty_search_results_returns_graceful_answer(self):
        tools = _make_tools(search_results=[])
        router = _make_router([
            _think_json(),
            _evaluate_json(confidence=0.0),
        ])
        agent = AgenticRAG(tools=tools, model_router=router)

        result = await agent.search("irrelevant question", max_iterations=1)

        assert isinstance(result, AgenticRAGResult)
        # Even with no results, answer must be a non-empty string
        assert isinstance(result.answer, str)
        assert len(result.answer) > 0

    @pytest.mark.asyncio
    async def test_sources_reflect_accumulated_results(self):
        sr = _search_result(doc_id="d1", chunk_id="c1", content="relevant content", score=0.9)
        tools = _make_tools(search_results=[sr])
        router = _make_router([_think_json(), _evaluate_json(confidence=0.95, answer="Yes.")])
        agent = AgenticRAG(tools=tools, model_router=router)

        result = await agent.search("question?")

        assert len(result.sources) >= 1
        assert result.sources[0].doc_id == "d1"
