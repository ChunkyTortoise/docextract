"""Tests for Sprint 1 quick fixes.

Streamlit is not installed in the test venv, so we mock the `streamlit` module
via sys.modules before importing any frontend code.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Streamlit sys.modules stub — must happen before any frontend import
# ---------------------------------------------------------------------------

def _make_streamlit_stub() -> MagicMock:
    stub = MagicMock(name="streamlit")

    class _FakeSessionState(dict):
        def __getattr__(self, key):
            return self.get(key)

        def __setattr__(self, key, val):
            self[key] = val

    stub.session_state = _FakeSessionState()
    stub.secrets = {}
    stub.columns.side_effect = lambda n, **kw: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
    return stub


_st_stub = _make_streamlit_stub()
sys.modules.setdefault("streamlit", _st_stub)
# Mock missing frontend deps
sys.modules.setdefault("pandas", MagicMock())


# ---------------------------------------------------------------------------
# Search results parsing tests
# ---------------------------------------------------------------------------

class TestSearchResultsParsing:
    """Test that search results handle both list and dict response shapes."""

    def _run_search(self, search_result, st_stub: MagicMock) -> None:
        """Helper: reload records module and invoke the search path."""
        sys.modules.pop("frontend.pages.records", None)
        sys.modules.pop("frontend.api_client", None)
        sys.modules["streamlit"] = st_stub

        import frontend.pages.records as mod
        import importlib
        importlib.reload(mod)

        mock_api = MagicMock()
        mock_api.search_records.return_value = search_result
        # Make export_records return bytes (for the export section)
        mock_api.export_records.return_value = b""
        mock_api.get_records.return_value = {"items": [], "total": 0, "has_next": False}

        with patch.object(mod, "api", mock_api):
            mod.render()

        return mock_api

    def _make_st(self, search_query: str = "test query") -> MagicMock:
        st = _make_streamlit_stub()
        st.text_input.return_value = search_query
        st.sidebar = MagicMock()
        st.sidebar.subheader = MagicMock()
        return st

    def test_list_response_extracts_record_key(self):
        """List response like [{"record": {...}, "similarity": 0.9}] is handled."""
        record = {"id": "rec-1", "document_type": "invoice", "confidence_score": 0.9}
        search_result = [{"record": record, "similarity": 0.9}]

        st = self._make_st()
        mock_api = self._run_search(search_result, st)
        mock_api.search_records.assert_called_once_with("test query", limit=10)

    def test_dict_response_uses_items_key(self):
        """Dict response like {"items": [...]} is handled (backwards compat)."""
        record = {"id": "rec-2", "document_type": "receipt", "confidence_score": 0.8}
        search_result = {"items": [record]}

        st = self._make_st()
        mock_api = self._run_search(search_result, st)
        mock_api.search_records.assert_called_once_with("test query", limit=10)

    def test_empty_list_response_shows_info(self):
        """Empty list search result shows info message."""
        st = self._make_st()
        mock_api = self._run_search([], st)
        st.info.assert_called()

    def test_empty_dict_response_shows_info(self):
        """Empty dict items search result shows info message."""
        st = self._make_st()
        mock_api = self._run_search({"items": []}, st)
        st.info.assert_called()
