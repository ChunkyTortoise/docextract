"""Unit tests for the optional spend-ceiling enforcement in AgenticRAG.

All Anthropic client calls and DB queries are mocked. Covers: ceiling math
in isolation, per-request enforcement, per-day enforcement, and the
flag-off no-op path (must be byte-identical to pre-ceiling behavior).
"""
from __future__ import annotations

import contextlib
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import anthropic
import pytest

from app.services.agentic_rag import AgenticRAG, _IterationState
from app.services.rag_tools import RagTools, SearchResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _search_result() -> SearchResult:
    return SearchResult(doc_id="d1", chunk_id="c1", content="sample content", score=0.9)


def _make_tools() -> RagTools:
    tools = MagicMock(spec=RagTools)
    results = [_search_result()]
    tools.search_vectors = AsyncMock(return_value=results)
    tools.search_bm25 = AsyncMock(return_value=results)
    tools.search_hybrid = AsyncMock(return_value=results)
    tools.lookup_metadata = AsyncMock(return_value={"doc_id": "d1"})
    return tools


def _think_json(action: str = "search_hybrid") -> str:
    return json.dumps({
        "thought": "Searching.",
        "action": action,
        "action_input": {"query": "test"},
    })


def _evaluate_json(confidence: float = 0.2) -> str:
    return json.dumps({
        "confidence": confidence,
        "reasoning": "not sure yet",
        "final_answer": "",
    })


def _make_passthrough_router() -> MagicMock:
    """A router whose call_with_fallback actually invokes call_fn (unlike the
    canned-response mock in test_agentic_rag.py), so real token usage flows
    through AgenticRAG._call_llm's cost accounting.
    """
    router = MagicMock()

    async def _call_with_fallback(operation, chain, call_fn):
        result = await call_fn(chain[0])
        return result, chain[0]

    router.call_with_fallback = _call_with_fallback
    return router


def _mock_anthropic_client(text: str, input_tokens: int, output_tokens: int) -> MagicMock:
    response = MagicMock()
    response.content = [MagicMock(text=text)]
    response.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    return client


@pytest.fixture(autouse=True)
def _reset_ceiling_settings():
    """Ensure spend ceiling settings are default (off) before/after each test."""
    from app.config import settings

    orig = (
        settings.spend_ceiling_enabled,
        settings.spend_ceiling_per_request_usd,
        settings.spend_ceiling_per_day_usd,
    )
    yield
    (
        settings.spend_ceiling_enabled,
        settings.spend_ceiling_per_request_usd,
        settings.spend_ceiling_per_day_usd,
    ) = orig


# ---------------------------------------------------------------------------
# Ceiling math (pure unit, no LLM calls)
# ---------------------------------------------------------------------------

class TestSpendCeilingMath:
    @pytest.mark.asyncio
    async def test_disabled_flag_never_triggers(self, monkeypatch):
        from app.config import settings

        settings.spend_ceiling_enabled = False
        settings.spend_ceiling_per_request_usd = 0.0  # would trip instantly if enabled

        agent = AgenticRAG(tools=_make_tools(), model_router=MagicMock())
        state = _IterationState(accumulated_cost_usd=Decimal("999"))

        reason = await agent._check_spend_ceiling(state, db=None)

        assert reason is None

    @pytest.mark.asyncio
    async def test_per_request_ceiling_trips_when_accumulated_cost_meets_it(self, monkeypatch):
        from app.config import settings

        settings.spend_ceiling_enabled = True
        settings.spend_ceiling_per_request_usd = 0.10
        settings.spend_ceiling_per_day_usd = 999.0

        agent = AgenticRAG(tools=_make_tools(), model_router=MagicMock())
        state = _IterationState(accumulated_cost_usd=Decimal("0.10"))

        reason = await agent._check_spend_ceiling(state, db=None)

        assert reason == "per_request_ceiling_exceeded"

    @pytest.mark.asyncio
    async def test_per_request_ceiling_not_tripped_below_threshold(self, monkeypatch):
        from app.config import settings

        settings.spend_ceiling_enabled = True
        settings.spend_ceiling_per_request_usd = 0.10
        settings.spend_ceiling_per_day_usd = 999.0

        agent = AgenticRAG(tools=_make_tools(), model_router=MagicMock())
        state = _IterationState(accumulated_cost_usd=Decimal("0.05"))

        reason = await agent._check_spend_ceiling(state, db=None)

        assert reason is None

    @pytest.mark.asyncio
    async def test_per_day_ceiling_trips_when_daily_total_meets_it(self, monkeypatch):
        from app.config import settings

        settings.spend_ceiling_enabled = True
        settings.spend_ceiling_per_request_usd = 999.0
        settings.spend_ceiling_per_day_usd = 5.0

        agent = AgenticRAG(tools=_make_tools(), model_router=MagicMock())
        agent._cost_tracker.get_cost_summary = AsyncMock(return_value={
            "claude-sonnet-4-6": {"extract": {"total_cost": 5.0, "avg_cost": 5.0, "call_count": 1}},
        })
        state = _IterationState()
        db = MagicMock()

        reason = await agent._check_spend_ceiling(state, db=db)

        assert reason == "per_day_ceiling_exceeded"
        agent._cost_tracker.get_cost_summary.assert_awaited_once_with(db, days=1)

    @pytest.mark.asyncio
    async def test_per_day_ceiling_not_tripped_below_threshold(self, monkeypatch):
        from app.config import settings

        settings.spend_ceiling_enabled = True
        settings.spend_ceiling_per_request_usd = 999.0
        settings.spend_ceiling_per_day_usd = 5.0

        agent = AgenticRAG(tools=_make_tools(), model_router=MagicMock())
        agent._cost_tracker.get_cost_summary = AsyncMock(return_value={
            "claude-sonnet-4-6": {"extract": {"total_cost": 1.0, "avg_cost": 1.0, "call_count": 1}},
        })
        state = _IterationState()

        reason = await agent._check_spend_ceiling(state, db=MagicMock())

        assert reason is None

    @pytest.mark.asyncio
    async def test_no_db_skips_daily_check(self, monkeypatch):
        """Without a db session, per-day check is skipped (not enforced), per-request still is."""
        from app.config import settings

        settings.spend_ceiling_enabled = True
        settings.spend_ceiling_per_request_usd = 999.0
        settings.spend_ceiling_per_day_usd = 0.0

        agent = AgenticRAG(tools=_make_tools(), model_router=MagicMock())
        state = _IterationState()

        reason = await agent._check_spend_ceiling(state, db=None)

        assert reason is None


# ---------------------------------------------------------------------------
# End-to-end enforcement inside the ReAct loop
# ---------------------------------------------------------------------------

class TestSpendCeilingEnforcementInLoop:
    @pytest.mark.asyncio
    async def test_per_request_ceiling_stops_loop_gracefully(self, monkeypatch):
        from app.config import settings

        settings.spend_ceiling_enabled = True
        settings.spend_ceiling_per_request_usd = 0.01
        settings.spend_ceiling_per_day_usd = 999.0

        # THINK call returns huge usage that alone blows past the per-request ceiling.
        client = _mock_anthropic_client(_think_json(), input_tokens=1_000_000, output_tokens=1_000_000)
        monkeypatch.setattr(anthropic, "AsyncAnthropic", MagicMock(return_value=client))

        router = _make_passthrough_router()
        agent = AgenticRAG(tools=_make_tools(), model_router=router)

        result = await agent.search("question?", max_iterations=3)

        assert result.degraded is True
        assert result.degradation_reason in {"per_request_ceiling_exceeded", "per_day_ceiling_exceeded"}
        assert isinstance(result.answer, str)
        assert len(result.answer) > 0
        # Should have stopped well short of the requested max_iterations.
        assert result.iterations < 3

    @pytest.mark.asyncio
    async def test_flag_off_is_byte_identical_no_op(self, monkeypatch):
        """With the flag off, no cost accounting happens and result is never degraded,
        even under a huge-usage response that would trip the ceiling if enabled."""
        from app.config import settings

        settings.spend_ceiling_enabled = False
        settings.spend_ceiling_per_request_usd = 0.0000001
        settings.spend_ceiling_per_day_usd = 0.0000001

        client = _mock_anthropic_client(
            json.dumps({"confidence": 0.95, "reasoning": "ok", "final_answer": "Found it."}),
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        monkeypatch.setattr(anthropic, "AsyncAnthropic", MagicMock(return_value=client))

        router = _make_passthrough_router()
        agent = AgenticRAG(tools=_make_tools(), model_router=router)

        result = await agent.search("question?", max_iterations=1)

        assert result.degraded is False
        assert result.degradation_reason is None
        assert result.iterations == 1

    @pytest.mark.asyncio
    async def test_per_day_ceiling_stops_loop_before_any_model_call(self, monkeypatch):
        from app.config import settings

        settings.spend_ceiling_enabled = True
        settings.spend_ceiling_per_request_usd = 999.0
        settings.spend_ceiling_per_day_usd = 1.0

        router = _make_passthrough_router()
        agent = AgenticRAG(tools=_make_tools(), model_router=router)
        agent._cost_tracker.get_cost_summary = AsyncMock(return_value={
            "claude-sonnet-4-6": {"extract": {"total_cost": 2.0, "avg_cost": 2.0, "call_count": 1}},
        })

        db = MagicMock()
        result = await agent.search("question?", max_iterations=3, db=db)

        assert result.degraded is True
        assert result.degradation_reason == "per_day_ceiling_exceeded"
        assert result.iterations == 0
        assert isinstance(result.answer, str)
        assert len(result.answer) > 0


# ---------------------------------------------------------------------------
# Endpoint-level wiring: the per-day branch is dead in production unless the
# FastAPI endpoints actually thread their request-scoped db session into
# agent.search / agent.search_stream. These tests exercise the real endpoint
# functions in app/api/agent_search.py (no HTTP layer needed) and assert the
# db session that FastAPI's Depends(get_db) would have injected is the same
# object AgenticRAG.search / search_stream receives.
# ---------------------------------------------------------------------------

class TestEndpointThreadsDbSession:
    @pytest.mark.asyncio
    async def test_agent_search_endpoint_passes_request_db_into_agent_search(self, monkeypatch):
        import app.api.agent_search as agent_search_module

        fake_agent = MagicMock()
        fake_result = MagicMock()
        fake_agent.search = AsyncMock(return_value=fake_result)
        monkeypatch.setattr(agent_search_module, "_build_agent", MagicMock(return_value=fake_agent))

        fake_db = MagicMock(name="request-scoped-db-session")
        request = agent_search_module.AgentSearchRequest(question="q?", max_iterations=2)

        result = await agent_search_module.agent_search(request, db=fake_db, api_key=MagicMock())

        fake_agent.search.assert_awaited_once()
        _, kwargs = fake_agent.search.call_args
        assert kwargs.get("db") is fake_db, (
            "agent_search endpoint must pass its request-scoped db session into "
            "agent.search(db=...) or the per-day spend ceiling branch never runs"
        )
        assert result is fake_result

    @pytest.mark.asyncio
    async def test_agent_search_stream_endpoint_passes_request_db_into_agent_search_stream(self, monkeypatch):
        import app.api.agent_search as agent_search_module

        async def _fake_stream(*args, **kwargs):
            yield MagicMock(event_type="step", model_dump=lambda **_: {})

        fake_agent = MagicMock()
        fake_agent.search_stream = MagicMock(side_effect=_fake_stream)
        monkeypatch.setattr(agent_search_module, "_build_agent", MagicMock(return_value=fake_agent))

        fake_db = MagicMock(name="request-scoped-db-session")
        request = agent_search_module.AgentSearchRequest(question="q?", max_iterations=2)

        response = await agent_search_module.agent_search_stream(request, db=fake_db, api_key=MagicMock())
        async for _ in response.body_iterator:
            pass

        fake_agent.search_stream.assert_called_once()
        _, kwargs = fake_agent.search_stream.call_args
        assert kwargs.get("db") is fake_db, (
            "agent_search_stream endpoint must pass its request-scoped db session into "
            "agent.search_stream(db=...) or the per-day spend ceiling branch never runs"
        )


# ---------------------------------------------------------------------------
# Cost persistence: _record_cost only accumulates in-memory on _IterationState,
# so the per-day ceiling's DB query (get_cost_summary reads llm_traces) never
# sees agentic-RAG spend. These tests verify _call_llm persists a trace row
# via the existing trace_llm_call pathway (app/services/llm_tracer.py) when a
# db session is available and the spend-ceiling flag is on, and skips it
# otherwise (flag off, or no db session).
# ---------------------------------------------------------------------------

class TestCostPersistence:
    @pytest.mark.asyncio
    async def test_call_llm_persists_trace_when_db_present_and_flag_on(self, monkeypatch):
        from app.config import settings
        from app.services import llm_tracer

        settings.spend_ceiling_enabled = True
        settings.spend_ceiling_per_request_usd = 999.0
        settings.spend_ceiling_per_day_usd = 999.0

        client = _mock_anthropic_client(_think_json(), input_tokens=100, output_tokens=50)
        monkeypatch.setattr(anthropic, "AsyncAnthropic", MagicMock(return_value=client))

        trace_calls: list[tuple] = []

        @contextlib.asynccontextmanager
        async def _fake_trace_llm_call(db, model, operation, *args, **kwargs):
            trace_calls.append((db, model, operation))
            ctx = MagicMock()
            yield ctx

        monkeypatch.setattr(llm_tracer, "trace_llm_call", _fake_trace_llm_call)

        router = _make_passthrough_router()
        agent = AgenticRAG(tools=_make_tools(), model_router=router)
        db = MagicMock()

        await agent._call_llm(
            system="sys",
            user="usr",
            models=["claude-sonnet-4-6"],
            operation="rag_think",
            state=_IterationState(),
            db=db,
        )

        assert trace_calls == [(db, "claude-sonnet-4-6", "rag_think")]

    @pytest.mark.asyncio
    async def test_call_llm_skips_trace_persistence_without_db(self, monkeypatch):
        from app.config import settings
        from app.services import llm_tracer

        settings.spend_ceiling_enabled = True
        settings.spend_ceiling_per_request_usd = 999.0
        settings.spend_ceiling_per_day_usd = 999.0

        client = _mock_anthropic_client(_think_json(), input_tokens=100, output_tokens=50)
        monkeypatch.setattr(anthropic, "AsyncAnthropic", MagicMock(return_value=client))

        trace_calls: list[tuple] = []

        @contextlib.asynccontextmanager
        async def _fake_trace_llm_call(db, model, operation, *args, **kwargs):
            trace_calls.append((db, model, operation))
            ctx = MagicMock()
            yield ctx

        monkeypatch.setattr(llm_tracer, "trace_llm_call", _fake_trace_llm_call)

        router = _make_passthrough_router()
        agent = AgenticRAG(tools=_make_tools(), model_router=router)

        await agent._call_llm(
            system="sys",
            user="usr",
            models=["claude-sonnet-4-6"],
            operation="rag_think",
            state=_IterationState(),
            db=None,
        )

        assert trace_calls == []

    @pytest.mark.asyncio
    async def test_call_llm_skips_trace_persistence_when_flag_off(self, monkeypatch):
        from app.config import settings
        from app.services import llm_tracer

        settings.spend_ceiling_enabled = False

        client = _mock_anthropic_client(_think_json(), input_tokens=100, output_tokens=50)
        monkeypatch.setattr(anthropic, "AsyncAnthropic", MagicMock(return_value=client))

        trace_calls: list[tuple] = []

        @contextlib.asynccontextmanager
        async def _fake_trace_llm_call(db, model, operation, *args, **kwargs):
            trace_calls.append((db, model, operation))
            ctx = MagicMock()
            yield ctx

        monkeypatch.setattr(llm_tracer, "trace_llm_call", _fake_trace_llm_call)

        router = _make_passthrough_router()
        agent = AgenticRAG(tools=_make_tools(), model_router=router)
        db = MagicMock()

        await agent._call_llm(
            system="sys",
            user="usr",
            models=["claude-sonnet-4-6"],
            operation="rag_think",
            state=_IterationState(),
            db=db,
        )

        assert trace_calls == []
