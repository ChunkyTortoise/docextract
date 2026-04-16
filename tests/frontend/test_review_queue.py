"""Tests for Sprint 4: review queue page and API client functions.

Streamlit is not installed in the test venv, so we mock the `streamlit` module
via sys.modules before importing any frontend code.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# Streamlit sys.modules stub
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
    stub.columns.side_effect = lambda n, **kw: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
    # tabs returns context managers
    tab_ctx = MagicMock()
    tab_ctx.__enter__ = MagicMock(return_value=MagicMock())
    tab_ctx.__exit__ = MagicMock(return_value=False)
    stub.tabs.return_value = [tab_ctx, tab_ctx]
    return stub


# Mock missing frontend deps (must happen before any frontend import)
sys.modules.setdefault("pandas", MagicMock())


# ---------------------------------------------------------------------------
# API client: review queue functions
# ---------------------------------------------------------------------------

class TestReviewQueueApiClient:
    def setup_method(self):
        sys.modules.pop("frontend.api_client", None)
        sys.modules.setdefault("streamlit", _make_st_stub())

    def _mock_get_client(self, response_data: dict | None = None) -> MagicMock:
        mock_response = MagicMock()
        mock_response.json.return_value = response_data or {}
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client.post.return_value = mock_response
        return mock_client

    def test_get_review_items_hits_correct_endpoint(self):
        """get_review_items GETs /review/queue."""
        mock_client = self._mock_get_client({"items": [], "total": 0})

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import get_review_items
            get_review_items()

        assert mock_client.get.call_args[0][0] == "/review/queue"

    def test_get_review_items_passes_filters(self):
        """get_review_items passes status, doc_type, page params."""
        mock_client = self._mock_get_client({"items": []})

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import get_review_items
            get_review_items(status="pending", doc_type="invoice", page=2, page_size=10)

        params = mock_client.get.call_args[1]["params"]
        assert params["status"] == "pending"
        assert params["doc_type"] == "invoice"
        assert params["page"] == 2
        assert params["page_size"] == 10

    def test_claim_review_item_posts_to_correct_endpoint(self):
        """claim_review_item POSTs to /review/queue/{id}/claim."""
        mock_client = self._mock_get_client({"status": "claimed"})

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import claim_review_item
            claim_review_item("item-1")

        mock_client.post.assert_called_once_with("/review/queue/item-1/claim")

    def test_approve_review_item_posts_to_correct_endpoint(self):
        """approve_review_item POSTs to /review/queue/{id}/approve."""
        mock_client = self._mock_get_client({"status": "approved"})

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import approve_review_item
            approve_review_item("item-2")

        mock_client.post.assert_called_once_with("/review/queue/item-2/approve")

    def test_correct_review_item_posts_corrections(self):
        """correct_review_item POSTs corrections payload to /review/queue/{id}/correct."""
        mock_client = self._mock_get_client({"status": "corrected"})
        corrections = {"total": "100.00", "vendor": "ACME"}

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import correct_review_item
            correct_review_item("item-3", corrections, reviewer_notes="looks good")

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[0][0] == "/review/queue/item-3/correct"
        payload = call_kwargs[1]["json"]
        assert payload["corrections"] == corrections
        assert payload["reviewer_notes"] == "looks good"

    def test_get_review_metrics_hits_correct_endpoint(self):
        """get_review_metrics GETs /review/metrics."""
        mock_client = self._mock_get_client({"pending": 5, "claimed": 2})

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import get_review_metrics
            result = get_review_metrics(stale_after_hours=48)

        assert mock_client.get.call_args[0][0] == "/review/metrics"
        assert mock_client.get.call_args[1]["params"]["stale_after_hours"] == 48
        assert result["pending"] == 5

    def test_review_queue_api_raises_on_http_error(self):
        """Review queue functions propagate HTTP errors."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=MagicMock()
        )
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import get_review_items
            with pytest.raises(httpx.HTTPStatusError):
                get_review_items()


# ---------------------------------------------------------------------------
# Review page render tests
# ---------------------------------------------------------------------------

class TestReviewPageRender:
    def setup_method(self):
        sys.modules.pop("frontend.pages.review", None)
        sys.modules.pop("frontend.api_client", None)

    def _render(self, demo_mode: bool, mock_api: MagicMock, st_stub: MagicMock) -> None:
        sys.modules["streamlit"] = st_stub
        import importlib

        import frontend.pages.review as mod
        importlib.reload(mod)
        env = {"DEMO_MODE": "true" if demo_mode else "false"}
        with patch.dict("os.environ", env):
            with patch.object(mod, "api", mock_api):
                mod.render()

    def _make_mock_api(self, queue_items: list | None = None) -> MagicMock:
        mock_api = MagicMock()
        mock_api.get_review_metrics.return_value = {
            "pending": 3,
            "claimed": 1,
            "total_open": 4,
            "sla_breach_rate": 0.1,
        }
        mock_api.get_review_items.return_value = {
            "items": queue_items or [],
            "total": len(queue_items or []),
        }
        return mock_api

    def test_metrics_section_rendered(self):
        """Queue metrics (Pending, Claimed, etc.) are shown."""
        st = _make_st_stub()
        st.text_input.return_value = ""
        st.selectbox.side_effect = ["All", "All"]
        st.number_input.return_value = 1
        mock_api = self._make_mock_api()

        self._render(demo_mode=False, mock_api=mock_api, st_stub=st)

        mock_api.get_review_metrics.assert_called_once()
        st.metric.assert_called()

    def test_queue_table_rendered_with_mock_items(self):
        """DataTable is rendered when queue has items."""
        items = [
            {
                "id": "item-1",
                "document_type": "invoice",
                "confidence_score": 0.85,
                "status": "pending",
                "assignee": None,
                "created_at": "2026-03-01T00:00:00",
            }
        ]
        st = _make_st_stub()
        st.text_input.return_value = ""
        st.selectbox.side_effect = ["All", "All"]
        st.number_input.return_value = 1
        sel = MagicMock()
        sel.selection.rows = []
        st.dataframe.return_value = sel
        mock_api = self._make_mock_api(queue_items=items)

        self._render(demo_mode=False, mock_api=mock_api, st_stub=st)

        mock_api.get_review_items.assert_called_once()
        st.dataframe.assert_called()

    def test_demo_mode_disables_action_buttons(self):
        """In demo mode, action buttons show info message instead."""
        st = _make_st_stub()
        st.text_input.return_value = ""
        st.selectbox.side_effect = ["All", "All"]
        st.number_input.return_value = 1
        mock_api = self._make_mock_api()

        self._render(demo_mode=True, mock_api=mock_api, st_stub=st)

        st.info.assert_called()
        # No claim/approve buttons
        button_labels = [call[0][0] for call in st.button.call_args_list]
        assert "Claim" not in button_labels
        assert "Approve" not in button_labels
