"""Tests for Sprint 3: ROI dashboard page and API client functions.

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
    tab_ctx = MagicMock()
    tab_ctx.__enter__ = MagicMock(return_value=MagicMock())
    tab_ctx.__exit__ = MagicMock(return_value=False)
    stub.tabs.return_value = [tab_ctx, tab_ctx]
    expander_ctx = MagicMock()
    expander_ctx.__enter__ = MagicMock(return_value=MagicMock())
    expander_ctx.__exit__ = MagicMock(return_value=False)
    stub.expander.return_value = expander_ctx
    return stub


# Mock missing frontend deps (must happen before any frontend import)
sys.modules.setdefault("plotly", MagicMock())
sys.modules.setdefault("plotly.express", MagicMock())
sys.modules.setdefault("plotly.graph_objects", MagicMock())


# ---------------------------------------------------------------------------
# API client: ROI functions
# ---------------------------------------------------------------------------

class TestRoiApiClient:
    def setup_method(self):
        sys.modules.pop("frontend.api_client", None)
        sys.modules.setdefault("streamlit", _make_st_stub())

    def _mock_get_client(self, response_data: dict) -> MagicMock:
        mock_response = MagicMock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client.post.return_value = mock_response
        return mock_client

    def test_get_roi_summary_hits_correct_endpoint(self):
        """get_roi_summary GETs /roi/summary."""
        mock_client = self._mock_get_client({"jobs_completed": 10, "dollars_saved": 500.0})

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import get_roi_summary
            result = get_roi_summary()

        mock_client.get.assert_called_once_with("/roi/summary", params={})
        assert result["jobs_completed"] == 10

    def test_get_roi_summary_passes_date_params(self):
        """get_roi_summary passes date_from and date_to as query params."""
        mock_client = self._mock_get_client({})

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import get_roi_summary
            get_roi_summary(date_from="2026-01-01", date_to="2026-03-01")

        call_params = mock_client.get.call_args[1]["params"]
        assert call_params["date_from"] == "2026-01-01"
        assert call_params["date_to"] == "2026-03-01"

    def test_get_roi_trends_passes_interval(self):
        """get_roi_trends passes interval param."""
        mock_client = self._mock_get_client({"items": []})

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import get_roi_trends
            get_roi_trends(interval="month")

        call_params = mock_client.get.call_args[1]["params"]
        assert call_params["interval"] == "month"
        assert mock_client.get.call_args[0][0] == "/roi/trends"

    def test_generate_report_posts_to_correct_endpoint(self):
        """generate_report POSTs to /roi/reports."""
        mock_client = self._mock_get_client({"report_id": "rpt-1"})

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import generate_report
            result = generate_report(format="json")

        mock_client.post.assert_called_once()
        assert mock_client.post.call_args[0][0] == "/roi/reports"
        assert result["report_id"] == "rpt-1"

    def test_list_reports_hits_correct_endpoint(self):
        """list_reports GETs /roi/reports with limit param."""
        mock_client = self._mock_get_client({"items": []})

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import list_reports
            list_reports(limit=5)

        mock_client.get.assert_called_once_with("/roi/reports", params={"limit": 5})

    def test_get_report_hits_correct_endpoint(self):
        """get_report GETs /roi/reports/{id}."""
        mock_client = self._mock_get_client({"report_id": "rpt-2"})

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import get_report
            result = get_report("rpt-2")

        mock_client.get.assert_called_once_with("/roi/reports/rpt-2")
        assert result["report_id"] == "rpt-2"

    def test_roi_api_raises_on_http_error(self):
        """ROI API functions propagate HTTP errors."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("frontend.api_client.get_client", return_value=mock_client):
            from frontend.api_client import get_roi_summary
            with pytest.raises(httpx.HTTPStatusError):
                get_roi_summary()


# ---------------------------------------------------------------------------
# ROI page render tests
# ---------------------------------------------------------------------------

class TestRoiPageRender:
    def setup_method(self):
        sys.modules.pop("frontend.pages.roi", None)
        sys.modules.pop("frontend.api_client", None)

    def _render(self, demo_mode: bool, mock_api: MagicMock, st_stub: MagicMock) -> None:
        sys.modules["streamlit"] = st_stub
        import frontend.pages.roi as mod
        import importlib
        importlib.reload(mod)
        env = {"DEMO_MODE": "true" if demo_mode else "false"}
        with patch.dict("os.environ", env):
            with patch.object(mod, "api", mock_api):
                mod.render()

    def _make_mock_api(self) -> MagicMock:
        mock_api = MagicMock()
        mock_api.get_roi_summary.return_value = {
            "jobs_completed": 42,
            "avg_confidence": 0.87,
            "minutes_saved": 120.0,
            "dollars_saved": 300.0,
            "net_value": 250.0,
        }
        mock_api.get_roi_trends.return_value = {"items": [
            {"period": "2026-01", "dollars_saved": 150.0, "net_value": 120.0},
        ]}
        mock_api.list_reports.return_value = {"items": []}
        return mock_api

    def test_kpi_cards_rendered_from_summary(self):
        """KPI metric cards are rendered using summary data."""
        st = _make_st_stub()
        st.date_input.return_value = None
        st.selectbox.return_value = "week"
        mock_api = self._make_mock_api()

        self._render(demo_mode=False, mock_api=mock_api, st_stub=st)

        mock_api.get_roi_summary.assert_called_once()
        st.metric.assert_called()

    def test_generate_report_button_hidden_in_demo_mode(self):
        """Generate Report button is not shown in demo mode."""
        st = _make_st_stub()
        st.date_input.return_value = None
        st.selectbox.return_value = "week"
        mock_api = self._make_mock_api()

        self._render(demo_mode=True, mock_api=mock_api, st_stub=st)

        # info should be shown instead of the generate button
        st.info.assert_called()
        button_labels = [call[0][0] for call in st.button.call_args_list]
        assert "Generate Report" not in button_labels

    def test_empty_state_no_crashes(self):
        """Page renders without error when API returns empty data."""
        st = _make_st_stub()
        st.date_input.return_value = None
        st.selectbox.return_value = "week"
        mock_api = MagicMock()
        mock_api.get_roi_summary.return_value = {}
        mock_api.get_roi_trends.return_value = {"items": []}
        mock_api.list_reports.return_value = {"items": []}

        # Should not raise
        self._render(demo_mode=False, mock_api=mock_api, st_stub=st)
