"""Tests for batch upload page and API client.

Streamlit is not installed in the test venv, so we mock the `streamlit` module
via sys.modules before importing any frontend code.
"""
from __future__ import annotations

import sys
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
    stub.form.return_value.__enter__ = MagicMock(return_value=MagicMock())
    stub.form.return_value.__exit__ = MagicMock(return_value=False)
    stub.columns.return_value = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
    expander_ctx = MagicMock()
    expander_ctx.__enter__ = MagicMock(return_value=MagicMock())
    expander_ctx.__exit__ = MagicMock(return_value=False)
    stub.expander.return_value = expander_ctx
    return stub


_st_stub = _make_streamlit_stub()
sys.modules.setdefault("streamlit", _st_stub)


# ---------------------------------------------------------------------------
# API client tests
# ---------------------------------------------------------------------------

class TestBatchUploadApiClient:
    def setup_method(self):
        # Remove cached module so each test starts fresh
        sys.modules.pop("frontend.api_client", None)

    def _make_mock_client(self, response_data: dict) -> MagicMock:
        mock_response = MagicMock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        return mock_client

    def test_batch_upload_posts_to_correct_endpoint(self):
        """batch_upload POSTs to /documents/batch with file tuples and priority."""
        mock_client = self._make_mock_client({"job_ids": ["job-1", "job-2"], "duplicates": []})

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import batch_upload

            files = [("a.pdf", b"bytes-a", "application/pdf"), ("b.pdf", b"bytes-b", "application/pdf")]
            result = batch_upload(files, priority="high")

        call_kwargs = mock_client.post.call_args
        assert call_kwargs[0][0] == "/documents/batch"
        assert call_kwargs[1]["data"] == {"priority": "high"}
        assert result == {"job_ids": ["job-1", "job-2"], "duplicates": []}

    def test_batch_upload_default_priority_is_normal(self):
        mock_client = self._make_mock_client({"job_ids": [], "duplicates": []})

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import batch_upload

            batch_upload([("x.pdf", b"data", "application/pdf")])

        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["data"] == {"priority": "normal"}

    def test_batch_upload_builds_file_tuples_correctly(self):
        """Each file is wrapped as ('files', (name, data, mime))."""
        mock_client = self._make_mock_client({"job_ids": ["j1"], "duplicates": []})

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import batch_upload

            batch_upload([("doc.pdf", b"content", "application/pdf")])

        files_arg = mock_client.post.call_args[1]["files"]
        assert files_arg == [("files", ("doc.pdf", b"content", "application/pdf"))]

    def test_batch_upload_raises_on_http_error(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400", request=MagicMock(), response=MagicMock()
        )
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import batch_upload

            with pytest.raises(httpx.HTTPStatusError):
                batch_upload([("f.pdf", b"d", "application/pdf")])


# ---------------------------------------------------------------------------
# Page render tests
# ---------------------------------------------------------------------------

def _fresh_st_stub(session_state: dict | None = None) -> MagicMock:
    """Return a fresh Streamlit stub with pre-populated session state.

    form_submit_button returns False by default so the submit path is not
    triggered unless a test explicitly enables it.
    """
    sys.modules.pop("frontend.pages.batch_upload", None)

    st = MagicMock(name="streamlit")

    class _SS(dict):
        def __getattr__(self, key):
            return self.get(key)

        def __setattr__(self, key, val):
            self[key] = val

    st.session_state = _SS(session_state or {})
    st.secrets = {}
    # Form context manager
    st.form.return_value.__enter__ = MagicMock(return_value=MagicMock())
    st.form.return_value.__exit__ = MagicMock(return_value=False)
    # Submit button returns False → no submit side effects
    st.form_submit_button.return_value = False
    st.columns.return_value = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
    expander_ctx = MagicMock()
    expander_ctx.__enter__ = MagicMock(return_value=MagicMock())
    expander_ctx.__exit__ = MagicMock(return_value=False)
    st.expander.return_value = expander_ctx
    return st


class TestBatchUploadPage:
    def setup_method(self):
        sys.modules.pop("frontend.pages.batch_upload", None)
        sys.modules.pop("frontend.api_client", None)
        sys.modules.pop("frontend.components.progress_bar", None)

    def test_render_demo_mode_shows_warning_and_returns(self):
        st = _fresh_st_stub()
        sys.modules["streamlit"] = st

        with patch.dict("os.environ", {"DEMO_MODE": "true"}):
            import importlib

            import frontend.pages.batch_upload as mod
            importlib.reload(mod)
            mod.render()

        st.warning.assert_called_once()
        st.form.assert_not_called()

    def test_render_empty_state_no_progress_section(self):
        """With no batch_job_ids, subheader for progress is never shown."""
        st = _fresh_st_stub({"batch_job_ids": []})
        sys.modules["streamlit"] = st

        mock_api = MagicMock()

        with patch.dict("os.environ", {"DEMO_MODE": "false"}):
            import importlib

            import frontend.pages.batch_upload as mod
            importlib.reload(mod)
            with patch.object(mod, "api", mock_api):
                with patch.object(mod, "display_progress", MagicMock()):
                    mod.render()

        st.subheader.assert_not_called()
        mock_api.get_job.assert_not_called()

    def test_render_with_active_jobs_calls_get_job(self):
        """With batch_job_ids set, get_job is called for each ID."""
        job_data = {"job_id": "job-abc", "status": "processing", "progress": 20}
        st = _fresh_st_stub({
            "batch_job_ids": ["job-abc"],
            "batch_filenames": {"job-abc": "file.pdf"},
            "batch_duplicates": [],
        })
        sys.modules["streamlit"] = st

        mock_api = MagicMock()
        mock_api.get_job.return_value = job_data

        with patch.dict("os.environ", {"DEMO_MODE": "false"}):
            import importlib

            import frontend.pages.batch_upload as mod
            importlib.reload(mod)
            with patch.object(mod, "api", mock_api):
                with patch.object(mod, "display_progress", MagicMock()):
                    mod.render()

        mock_api.get_job.assert_called_once_with("job-abc")
        st.expander.assert_called_once()

    def test_render_all_completed_shows_success(self):
        """When all jobs are terminal, a success message is shown."""
        job_data = {"job_id": "job-xyz", "status": "completed", "progress": 100}
        st = _fresh_st_stub({
            "batch_job_ids": ["job-xyz"],
            "batch_filenames": {"job-xyz": "done.pdf"},
            "batch_duplicates": [],
        })
        sys.modules["streamlit"] = st

        mock_api = MagicMock()
        mock_api.get_job.return_value = job_data

        with patch.dict("os.environ", {"DEMO_MODE": "false"}):
            import importlib

            import frontend.pages.batch_upload as mod
            importlib.reload(mod)
            with patch.object(mod, "api", mock_api):
                with patch.object(mod, "display_progress", MagicMock()):
                    mod.render()

        st.success.assert_called_once()
        st.button.assert_called_once()
