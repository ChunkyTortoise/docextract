"""Unit tests for streaming agent search (search_stream + SSE endpoint)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.agentic_rag import (
    AgenticRAG,
    AgenticRAGResult,
    ReasoningStep,
    StreamEvent,
)
from app.services.rag_tools import RagTools, SearchResult

# ---------------------------------------------------------------------------
# Helpers (reused from test_agentic_rag.py)
# ---------------------------------------------------------------------------

def _search_result(doc_id="d1", chunk_id="c1", content="sample content", score=0.9) -> SearchResult:
    return SearchResult(doc_id=doc_id, chunk_id=chunk_id, content=content, score=score)


def _make_tools(search_results: list[SearchResult] | None = None) -> RagTools:
    tools = MagicMock(spec=RagTools)
    results = search_results or [_search_result()]
    tools.search_vectors = AsyncMock(return_value=results)
    tools.search_bm25 = AsyncMock(return_value=results)
    tools.search_hybrid = AsyncMock(return_value=results)
    tools.lookup_metadata = AsyncMock(return_value={"doc_id": "d1", "document_type": "invoice"})
    tools.rerank_results = AsyncMock(side_effect=lambda q, r: r)
    return tools


def _make_router(responses: list[str]) -> MagicMock:
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
# StreamEvent model tests
# ---------------------------------------------------------------------------

class TestStreamEvent:
    def test_step_event_has_step(self):
        step = ReasoningStep(
            step=1, thought="t", action="search_hybrid",
            action_input={"query": "q"}, observation="obs", confidence=0.9,
        )
        event = StreamEvent(event_type="step", step=step)
        assert event.event_type == "step"
        assert event.step is not None
        assert event.result is None

    def test_done_event_has_result(self):
        result = AgenticRAGResult(
            answer="a", sources=[], reasoning_trace=[], iterations=1,
            confidence=0.9, tools_used=[], question="q",
        )
        event = StreamEvent(event_type="done", result=result)
        assert event.event_type == "done"
        assert event.result is not None
        assert event.step is None


# ---------------------------------------------------------------------------
# search_stream yields reasoning steps
# ---------------------------------------------------------------------------

class TestSearchStream:
    @pytest.mark.asyncio
    async def test_stream_yields_step_events(self):
        tools = _make_tools()
        router = _make_router([_think_json(), _evaluate_json(confidence=0.95, answer="Got it.")])
        agent = AgenticRAG(tools=tools, model_router=router)

        events = []
        async for event in agent.search_stream("What is the total?", max_iterations=3):
            events.append(event)

        # At least one step + one done
        assert len(events) >= 2
        step_events = [e for e in events if e.event_type == "step"]
        done_events = [e for e in events if e.event_type == "done"]
        assert len(step_events) >= 1
        assert len(done_events) == 1

    @pytest.mark.asyncio
    async def test_stream_step_contains_reasoning_step(self):
        tools = _make_tools()
        router = _make_router([_think_json(), _evaluate_json(confidence=0.9, answer="Yes.")])
        agent = AgenticRAG(tools=tools, model_router=router)

        events = []
        async for event in agent.search_stream("question?"):
            events.append(event)

        step_event = events[0]
        assert step_event.event_type == "step"
        assert isinstance(step_event.step, ReasoningStep)
        assert step_event.step.step == 1
        assert step_event.step.action == "search_hybrid"

    @pytest.mark.asyncio
    async def test_stream_done_contains_full_result(self):
        tools = _make_tools()
        router = _make_router([_think_json(), _evaluate_json(confidence=0.9, answer="Done.")])
        agent = AgenticRAG(tools=tools, model_router=router)

        events = []
        async for event in agent.search_stream("question?"):
            events.append(event)

        done_event = events[-1]
        assert done_event.event_type == "done"
        assert isinstance(done_event.result, AgenticRAGResult)
        assert done_event.result.answer == "Done."
        assert done_event.result.question == "question?"

    @pytest.mark.asyncio
    async def test_stream_respects_max_iterations(self):
        tools = _make_tools()
        # Always low confidence -- should stop at max_iterations=2
        responses = [
            _think_json(), _evaluate_json(confidence=0.2),
            _think_json(), _evaluate_json(confidence=0.2),
            _think_json(), _evaluate_json(confidence=0.2),
        ]
        router = _make_router(responses)
        agent = AgenticRAG(tools=tools, model_router=router)

        events = []
        async for event in agent.search_stream("q?", max_iterations=2):
            events.append(event)

        step_events = [e for e in events if e.event_type == "step"]
        assert len(step_events) == 2

    @pytest.mark.asyncio
    async def test_stream_stops_at_confidence_threshold(self):
        tools = _make_tools()
        router = _make_router([_think_json(), _evaluate_json(confidence=0.95, answer="Found.")])
        agent = AgenticRAG(tools=tools, model_router=router)

        events = []
        async for event in agent.search_stream("q?", max_iterations=5):
            events.append(event)

        step_events = [e for e in events if e.event_type == "step"]
        assert len(step_events) == 1  # stopped after 1 iteration

    @pytest.mark.asyncio
    async def test_stream_and_search_produce_same_result(self):
        """Deterministic mocks: stream and batch should return identical answers."""
        tools = _make_tools()
        responses = [
            _think_json("search_vectors"),
            _evaluate_json(confidence=0.4),
            _think_json("search_bm25"),
            _evaluate_json(confidence=0.92, answer="Final answer."),
        ]

        # Run batch
        router1 = _make_router(list(responses))
        agent1 = AgenticRAG(tools=tools, model_router=router1)
        batch_result = await agent1.search("q?", max_iterations=3)

        # Run stream
        router2 = _make_router(list(responses))
        agent2 = AgenticRAG(tools=tools, model_router=router2)
        stream_events = []
        async for event in agent2.search_stream("q?", max_iterations=3):
            stream_events.append(event)

        stream_result = stream_events[-1].result
        assert stream_result is not None
        assert stream_result.answer == batch_result.answer
        assert stream_result.iterations == batch_result.iterations
        assert stream_result.confidence == batch_result.confidence
        assert len(stream_result.reasoning_trace) == len(batch_result.reasoning_trace)

    @pytest.mark.asyncio
    async def test_stream_multi_iteration_yields_incremental_steps(self):
        tools = _make_tools()
        responses = [
            _think_json("search_vectors"),
            _evaluate_json(confidence=0.3),
            _think_json("search_bm25"),
            _evaluate_json(confidence=0.5),
            _think_json("search_hybrid"),
            _evaluate_json(confidence=0.9, answer="Complete."),
        ]
        router = _make_router(responses)
        agent = AgenticRAG(tools=tools, model_router=router)

        events = []
        async for event in agent.search_stream("q?", max_iterations=5):
            events.append(event)

        step_events = [e for e in events if e.event_type == "step"]
        assert len(step_events) == 3
        # Steps should be numbered sequentially
        for i, se in enumerate(step_events, start=1):
            assert se.step is not None
            assert se.step.step == i
