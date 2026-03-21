"""Tests for Sprint 2: job cancel and document delete UI.

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
    return stub


# Mock missing frontend deps (must happen before any frontend import)
sys.modules.setdefault("pandas", MagicMock())


# ---------------------------------------------------------------------------
# API client: cancel_job
# ---------------------------------------------------------------------------

class TestCancelJobApiClient:
    def setup_method(self):
        sys.modules.pop("frontend.api_client", None)

    def _make_mock_client(self, response_data: dict | None = None, status_code: int = 200) -> MagicMock:
        mock_response = MagicMock()
        mock_response.json.return_value = response_data or {"status": "cancelled"}
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.patch.return_value = mock_response
        mock_client.delete.return_value = mock_response
        return mock_client

    def test_cancel_job_sends_patch_with_cancel_action(self):
        """cancel_job sends PATCH /jobs/{id} with {"action": "cancel"}."""
        mock_client = self._make_mock_client({"status": "cancelled"})

        sys.modules.setdefault("streamlit", _make_st_stub())
        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import cancel_job
            result = cancel_job("job-123")

        mock_client.patch.assert_called_once_with("/jobs/job-123", json={"action": "cancel"})
        assert result == {"status": "cancelled"}

    def test_cancel_job_raises_on_http_error(self):
        """cancel_job propagates HTTP errors."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "409", request=MagicMock(), response=MagicMock()
        )
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.patch.return_value = mock_response

        sys.modules.setdefault("streamlit", _make_st_stub())
        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import cancel_job
            with pytest.raises(httpx.HTTPStatusError):
                cancel_job("job-bad")


# ---------------------------------------------------------------------------
# API client: delete_document
# ---------------------------------------------------------------------------

class TestDeleteDocumentApiClient:
    def setup_method(self):
        sys.modules.pop("frontend.api_client", None)

    def test_delete_document_sends_delete_request(self):
        """delete_document sends DELETE /documents/{id}."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.delete.return_value = mock_response

        sys.modules.setdefault("streamlit", _make_st_stub())
        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import delete_document
            delete_document("doc-456")

        mock_client.delete.assert_called_once_with("/documents/doc-456")

    def test_delete_document_raises_on_http_error(self):
        """delete_document propagates HTTP errors (e.g. 404)."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.delete.return_value = mock_response

        sys.modules.setdefault("streamlit", _make_st_stub())
        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import delete_document
            with pytest.raises(httpx.HTTPStatusError):
                delete_document("doc-bad")


# ---------------------------------------------------------------------------
# Progress page: cancel button visibility
# ---------------------------------------------------------------------------

class TestProgressPageCancelButton:
    def setup_method(self):
        sys.modules.pop("frontend.pages.progress", None)
        sys.modules.pop("frontend.api_client", None)
        sys.modules.pop("frontend.components.progress_bar", None)

    def _render_with_job(self, job_data: dict, st_stub: MagicMock) -> MagicMock:
        sys.modules["streamlit"] = st_stub
        import frontend.pages.progress as mod
        import importlib
        importlib.reload(mod)

        mock_api = MagicMock()
        mock_api.get_job.return_value = job_data

        with patch.object(mod, "api", mock_api):
            with patch.object(mod, "display_progress", MagicMock()):
                with patch("time.sleep"):
                    mod.render()

        return mock_api

    def test_cancel_button_shown_for_processing_job(self):
        """Cancel button is shown when job status is 'processing'."""
        job = {"job_id": "j1", "status": "processing", "progress": 40}
        st = _make_st_stub({"current_job_id": "j1"})
        st.checkbox.return_value = False  # no auto-refresh

        self._render_with_job(job, st)

        # st.button should be called (at least the Cancel Job button)
        st.button.assert_called()
        button_labels = [call[0][0] for call in st.button.call_args_list]
        assert "Cancel Job" in button_labels

    def test_cancel_button_not_shown_for_completed_job(self):
        """Cancel button is NOT shown when job status is 'completed'."""
        job = {"job_id": "j2", "status": "completed", "progress": 100}
        st = _make_st_stub({"current_job_id": "j2"})
        st.checkbox.return_value = False

        self._render_with_job(job, st)

        button_labels = [call[0][0] for call in st.button.call_args_list]
        assert "Cancel Job" not in button_labels

    def test_cancel_button_not_shown_for_failed_job(self):
        """Cancel button is NOT shown when job status is 'failed'."""
        job = {"job_id": "j3", "status": "failed", "error_message": "oops"}
        st = _make_st_stub({"current_job_id": "j3"})
        st.checkbox.return_value = False

        self._render_with_job(job, st)

        button_labels = [call[0][0] for call in st.button.call_args_list]
        assert "Cancel Job" not in button_labels


# ---------------------------------------------------------------------------
# Records page: delete button guarded by demo mode
# ---------------------------------------------------------------------------

class TestRecordsDeleteDemoGuard:
    def setup_method(self):
        sys.modules.pop("frontend.pages.records", None)
        sys.modules.pop("frontend.api_client", None)

    def test_delete_button_hidden_in_demo_mode(self):
        """Delete button is not rendered when DEMO_MODE=true."""
        st = _make_st_stub()
        st.text_input.return_value = ""  # no search
        st.selectbox.side_effect = ["All", "All"]
        st.slider.return_value = 0.0
        st.number_input.return_value = 1
        # dataframe returns no selection
        sel = MagicMock()
        sel.selection.rows = []
        st.dataframe.return_value = sel
        st.sidebar = MagicMock()
        sys.modules["streamlit"] = st

        item = {"id": "rec-1", "document_type": "invoice", "confidence_score": 0.95,
                "needs_review": False, "review_status": "approved", "created_at": "2026-01-01"}

        import frontend.pages.records as mod
        import importlib
        importlib.reload(mod)

        mock_api = MagicMock()
        mock_api.get_records.return_value = {"items": [item], "total": 1, "has_next": False}
        mock_api.export_records.return_value = b""

        with patch.dict("os.environ", {"DEMO_MODE": "true"}):
            with patch.object(mod, "api", mock_api):
                mod.render()

        # Simulate row selection — re-render with selection
        sel2 = MagicMock()
        sel2.selection.rows = [0]
        st.dataframe.return_value = sel2
        st.columns.return_value = [MagicMock(), MagicMock(), MagicMock()]

        with patch.dict("os.environ", {"DEMO_MODE": "true"}):
            with patch.object(mod, "api", mock_api):
                mod._render_records_table([item])

        # Delete button should NOT appear in demo mode
        button_labels = [call[0][0] for call in st.button.call_args_list]
        assert "Delete" not in button_labels
