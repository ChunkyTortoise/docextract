"""Tests for Sprint 3: Agent Trace Viewer page and agent_search API client.

Streamlit and plotly are not installed in the test venv, so we mock them via
sys.modules before importing any frontend code.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Stubs — must be set before any frontend import
# ---------------------------------------------------------------------------

def _make_st_stub(session_state: dict | None = None) -> MagicMock:
    stub = MagicMock(name="streamlit")

    class _SS(dict):
        def __getattr__(self, key):
            return self.get(key)

        def __setattr__(self, key, val):
            self[key] = val

    stub.session_state = _SS(session_state or {})
    stub.secrets = {}
    stub.columns.side_effect = lambda n, **kw: [
        MagicMock() for _ in range(n if isinstance(n, int) else len(n))
    ]
    expander_ctx = MagicMock()
    expander_ctx.__enter__ = MagicMock(return_value=MagicMock())
    expander_ctx.__exit__ = MagicMock(return_value=False)
    stub.expander.return_value = expander_ctx

    form_ctx = MagicMock()
    form_ctx.__enter__ = MagicMock(return_value=MagicMock())
    form_ctx.__exit__ = MagicMock(return_value=False)
    stub.form.return_value = form_ctx

    stub.form_submit_button.return_value = False
    stub.text_input.return_value = "What is the total amount due?"
    stub.slider.return_value = 3
    return stub


# Install stubs before any import
sys.modules.setdefault("streamlit", _make_st_stub())
sys.modules.setdefault("plotly", MagicMock())
sys.modules.setdefault("plotly.express", MagicMock())
sys.modules.setdefault("plotly.graph_objects", MagicMock())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEMO_FILE = (
    Path(__file__).parent.parent.parent
    / "frontend"
    / "demo_data"
    / "agent_trace_demo.json"
)

_MINIMAL_RESULT: dict = {
    "answer": "The total is $5,286.50.",
    "sources": [
        {
            "doc_id": "doc-1",
            "chunk_id": "doc-1-chunk-1",
            "content": "Total Amount Due: $5,286.50.",
            "score": 0.94,
            "metadata": {},
        }
    ],
    "reasoning_trace": [
        {
            "step": 1,
            "thought": "BM25 for numeric lookup.",
            "action": "search_bm25",
            "action_input": {"query": "invoice total", "top_k": 5},
            "observation": "Found 2 results. Top: Total Amount Due: $5,286.50.",
            "confidence": 0.91,
        },
        {
            "step": 2,
            "thought": "Confidence exceeds threshold.",
            "action": "search_bm25",
            "action_input": {"query": "invoice total", "top_k": 5},
            "observation": "Confidence threshold met. Terminating.",
            "confidence": 0.94,
        },
    ],
    "iterations": 2,
    "confidence": 0.94,
    "tools_used": ["search_bm25"],
    "question": "What is the total amount due on the invoice?",
}


def _fresh_modules() -> None:
    """Remove cached frontend modules so each test gets a clean import."""
    for key in list(sys.modules.keys()):
        if key.startswith("frontend"):
            del sys.modules[key]
    # Re-install a fresh st stub so call counts don't bleed between tests
    sys.modules["streamlit"] = _make_st_stub()


# ---------------------------------------------------------------------------
# Test 1 — demo data file exists and is valid JSON
# ---------------------------------------------------------------------------

class TestDemoDataFile:
    def test_demo_file_exists(self):
        assert _DEMO_FILE.exists(), f"Demo file not found: {_DEMO_FILE}"

    def test_demo_file_is_valid_json(self):
        data = json.loads(_DEMO_FILE.read_text())
        assert isinstance(data, dict)

    def test_demo_file_has_required_keys(self):
        data = json.loads(_DEMO_FILE.read_text())
        for key in ("answer", "sources", "reasoning_trace", "iterations", "confidence", "tools_used", "question"):
            assert key in data, f"Missing key: {key}"

    def test_demo_file_reasoning_trace_has_action_input_dict(self):
        data = json.loads(_DEMO_FILE.read_text())
        for step in data["reasoning_trace"]:
            assert isinstance(step["action_input"], dict), (
                f"action_input should be dict, got {type(step['action_input'])}"
            )


# ---------------------------------------------------------------------------
# Test 2 — _load_trace: API available
# ---------------------------------------------------------------------------

class TestLoadTraceApiAvailable:
    def setup_method(self):
        _fresh_modules()

    def test_load_trace_calls_agent_search_when_question_given(self):
        mock_api = MagicMock()
        mock_api.agent_search.return_value = _MINIMAL_RESULT

        with patch.dict(sys.modules, {"frontend.api_client": mock_api}):
            from frontend.pages.agent_trace import _load_trace
            result = _load_trace("What is the total?", 3)

        mock_api.agent_search.assert_called_once_with(
            "What is the total?", max_iterations=3
        )
        assert result == _MINIMAL_RESULT

    def test_load_trace_passes_max_iterations(self):
        mock_api = MagicMock()
        mock_api.agent_search.return_value = _MINIMAL_RESULT

        with patch.dict(sys.modules, {"frontend.api_client": mock_api}):
            from frontend.pages.agent_trace import _load_trace
            _load_trace("Any question?", 5)

        mock_api.agent_search.assert_called_once_with("Any question?", max_iterations=5)


# ---------------------------------------------------------------------------
# Test 3 — _load_trace: API unavailable (falls back to demo data)
# ---------------------------------------------------------------------------

class TestLoadTraceApiFallback:
    def setup_method(self):
        _fresh_modules()

    def test_falls_back_to_demo_when_api_raises(self):
        mock_api = MagicMock()
        mock_api.agent_search.side_effect = Exception("connection refused")

        with patch.dict(sys.modules, {"frontend.api_client": mock_api}):
            from frontend.pages.agent_trace import _load_trace
            result = _load_trace("Any question?", 3)

        # Should have fallen back to demo data
        assert result is not None
        assert "reasoning_trace" in result

    def test_load_trace_no_question_loads_demo_directly(self):
        """When question=None, API is never called; demo data returned."""
        mock_api = MagicMock()

        with patch.dict(sys.modules, {"frontend.api_client": mock_api}):
            from frontend.pages.agent_trace import _load_trace
            result = _load_trace(None, 3)

        mock_api.agent_search.assert_not_called()
        assert result is not None
        assert result.get("answer")


# ---------------------------------------------------------------------------
# Test 4 — _render_trace: KPI metrics
# ---------------------------------------------------------------------------

def _capture_col_metrics(st_stub: MagicMock, result: dict) -> list[tuple]:
    """Run _render_trace and collect all (label, value) metric calls from columns."""
    from frontend.pages.agent_trace import _render_trace

    captured_cols: list[list[MagicMock]] = []

    def _col_side_effect(n, **kw):
        cols = [MagicMock(name=f"col{i}") for i in range(n if isinstance(n, int) else len(n))]
        captured_cols.append(cols)
        return cols

    st_stub.columns.side_effect = _col_side_effect
    _render_trace(result)

    calls: list[tuple] = []
    for col_group in captured_cols:
        for col in col_group:
            for c in col.metric.call_args_list:
                if c.args:
                    calls.append((c.args[0], c.args[1] if len(c.args) > 1 else None))
    return calls


class TestRenderTraceKpis:
    def setup_method(self):
        _fresh_modules()

    def test_kpi_iterations_correct(self):
        st = sys.modules["streamlit"]
        calls = _capture_col_metrics(st, _MINIMAL_RESULT)
        labels = {label: val for label, val in calls}
        assert "Iterations" in labels, f"Iterations not in metric calls: {labels}"
        assert labels["Iterations"] == 2

    def test_kpi_confidence_formatted_as_percent(self):
        st = sys.modules["streamlit"]
        calls = _capture_col_metrics(st, _MINIMAL_RESULT)
        labels = {label: val for label, val in calls}
        assert "Final Confidence" in labels, f"Final Confidence not in metric calls: {labels}"
        assert "94%" in labels["Final Confidence"]


# ---------------------------------------------------------------------------
# Test 5 — _render_trace: expanders called per step
# ---------------------------------------------------------------------------

class TestRenderTraceExpanders:
    def setup_method(self):
        _fresh_modules()

    def test_expander_called_for_each_step(self):
        st = sys.modules["streamlit"]
        from frontend.pages.agent_trace import _render_trace

        _render_trace(_MINIMAL_RESULT)

        assert st.expander.call_count >= 2  # 2 trace steps + 1 source

    def test_expander_called_for_sources(self):
        st = sys.modules["streamlit"]
        from frontend.pages.agent_trace import _render_trace

        result = dict(_MINIMAL_RESULT)
        result["sources"] = [
            {"doc_id": "d1", "chunk_id": "c1", "content": "text 1", "score": 0.9, "metadata": {}},
            {"doc_id": "d2", "chunk_id": "c2", "content": "text 2", "score": 0.8, "metadata": {}},
        ]
        _render_trace(result)

        # At least 4 expanders: 2 trace steps + 2 sources
        assert st.expander.call_count >= 4


# ---------------------------------------------------------------------------
# Test 6 — _render_trace: empty trace handled gracefully
# ---------------------------------------------------------------------------

class TestRenderTraceEdgeCases:
    def setup_method(self):
        _fresh_modules()

    def test_empty_trace_no_error(self):
        from frontend.pages.agent_trace import _render_trace

        result = {
            "answer": "Some answer",
            "sources": [],
            "reasoning_trace": [],
            "iterations": 0,
            "confidence": 0.0,
            "tools_used": [],
            "question": "Q?",
        }
        # Should not raise
        _render_trace(result)

    def test_single_step_no_trajectory_chart(self):
        """With only 1 step, the confidence trajectory chart should NOT be rendered."""
        st = sys.modules["streamlit"]
        from frontend.pages.agent_trace import _render_trace

        result = dict(_MINIMAL_RESULT)
        result["reasoning_trace"] = [_MINIMAL_RESULT["reasoning_trace"][0]]
        result["iterations"] = 1

        go_mock = sys.modules["plotly.graph_objects"]
        go_mock.Figure.reset_mock()

        _render_trace(result)

        # plotly Figure should not have been used for trajectory
        # (it may be used for other things, but scatter trace won't be added)
        # We verify by checking subheader was not called with trajectory text
        subheader_calls = [str(c) for c in st.subheader.call_args_list]
        assert not any("Trajectory" in s for s in subheader_calls)

    def test_three_steps_renders_trajectory_chart(self):
        """With 3 steps, the confidence trajectory chart IS rendered."""
        st = sys.modules["streamlit"]
        from frontend.pages.agent_trace import _render_trace

        three_step_result = dict(_MINIMAL_RESULT)
        three_step_result["reasoning_trace"] = [
            {
                "step": 1, "thought": "T1", "action": "search_bm25",
                "action_input": {"query": "q"}, "observation": "O1", "confidence": 0.6,
            },
            {
                "step": 2, "thought": "T2", "action": "search_hybrid",
                "action_input": {"query": "q"}, "observation": "O2", "confidence": 0.75,
            },
            {
                "step": 3, "thought": "T3", "action": "search_hybrid",
                "action_input": {"query": "q"}, "observation": "O3", "confidence": 0.91,
            },
        ]
        three_step_result["iterations"] = 3

        _render_trace(three_step_result)

        subheader_calls = [str(c) for c in st.subheader.call_args_list]
        assert any("Trajectory" in s for s in subheader_calls)

    def test_missing_fields_no_key_error(self):
        """A result dict with minimal fields must not raise KeyError."""
        from frontend.pages.agent_trace import _render_trace

        _render_trace({})  # completely empty

    def test_empty_answer_shows_warning(self):
        st = sys.modules["streamlit"]
        from frontend.pages.agent_trace import _render_trace

        result = dict(_MINIMAL_RESULT)
        result["answer"] = ""
        _render_trace(result)

        st.warning.assert_called()

    def test_non_empty_answer_shows_success(self):
        st = sys.modules["streamlit"]
        from frontend.pages.agent_trace import _render_trace

        _render_trace(_MINIMAL_RESULT)

        # st.success is called for the answer (and for observations inside expanders)
        st.success.assert_called()

    def test_tool_count_deduplicates(self):
        """tools_used list with duplicates should report unique count."""
        st = sys.modules["streamlit"]

        result = dict(_MINIMAL_RESULT)
        result["tools_used"] = ["search_bm25", "search_bm25", "search_hybrid"]

        calls = _capture_col_metrics(st, result)
        labels = {label: val for label, val in calls}
        assert "Tools Used" in labels, f"Tools Used not in metric calls: {labels}"
        assert labels["Tools Used"] == 2  # set(["search_bm25", "search_hybrid"]) = 2

    def test_empty_sources_no_sources_section(self):
        st = sys.modules["streamlit"]
        from frontend.pages.agent_trace import _render_trace

        result = dict(_MINIMAL_RESULT)
        result["sources"] = []
        _render_trace(result)

        subheader_calls = [str(c) for c in st.subheader.call_args_list]
        assert not any("Sources" in s for s in subheader_calls)

    def test_multiple_sources_renders_expanders(self):
        st = sys.modules["streamlit"]
        from frontend.pages.agent_trace import _render_trace

        result = dict(_MINIMAL_RESULT)
        result["reasoning_trace"] = []  # keep expander count clean
        result["sources"] = [
            {"doc_id": "d1", "chunk_id": "c1", "content": "text 1", "score": 0.9, "metadata": {}},
            {"doc_id": "d2", "chunk_id": "c2", "content": "text 2", "score": 0.85, "metadata": {}},
            {"doc_id": "d3", "chunk_id": "c3", "content": "text 3", "score": 0.7, "metadata": {}},
        ]
        _render_trace(result)

        subheader_calls = [str(c) for c in st.subheader.call_args_list]
        assert any("Sources" in s for s in subheader_calls)
        assert st.expander.call_count >= 3


# ---------------------------------------------------------------------------
# Test 7 — agent_search in api_client
# ---------------------------------------------------------------------------

class TestAgentSearchApiClient:
    def setup_method(self):
        for key in list(sys.modules.keys()):
            if key == "frontend.api_client":
                del sys.modules[key]
        sys.modules["streamlit"] = _make_st_stub(
            {"api_key": "test-key", "authenticated": True}
        )

    def _mock_client_response(self, response_data: dict) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.json.return_value = response_data
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        return mock_client

    def test_agent_search_posts_to_agent_search_endpoint(self):
        mock_client = self._mock_client_response(_MINIMAL_RESULT)

        with patch("frontend.api_client.get_client", return_value=mock_client):
            import frontend.api_client as api
            result = api.agent_search("What is the total?", max_iterations=3)

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert "/agent-search" in call_kwargs.args[0]
        assert result == _MINIMAL_RESULT

    def test_agent_search_sends_correct_payload(self):
        mock_client = self._mock_client_response(_MINIMAL_RESULT)

        with patch("frontend.api_client.get_client", return_value=mock_client):
            import frontend.api_client as api
            api.agent_search("Test question", doc_ids=["doc-1"], max_iterations=2)

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
        assert payload["question"] == "Test question"
        assert payload["doc_ids"] == ["doc-1"]
        assert payload["max_iterations"] == 2

    def test_agent_search_uses_60s_timeout(self):
        mock_client = self._mock_client_response(_MINIMAL_RESULT)

        with patch("frontend.api_client.get_client", return_value=mock_client):
            import frontend.api_client as api
            api.agent_search("Q?")

        call_kwargs = mock_client.post.call_args
        timeout = call_kwargs.kwargs.get("timeout")
        assert timeout == 60.0
