"""Screen 6: Analytics dashboard."""
from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import frontend.api_client as api
from frontend.theme import PLOTLY_DARK
try:
    from streamlit_extras.stylable_container import stylable_container as _stylable
    _HAS_EXTRAS = True
except ImportError:
    _HAS_EXTRAS = False

_METRIC_CSS = """
{
    background: rgba(99, 102, 241, 0.08);
    border: 1px solid rgba(99, 102, 241, 0.2);
    border-radius: 10px;
    padding: 0.75rem 0.5rem;
}
"""


def _compute_processing_times(jobs: list[dict]) -> list[float]:
    """Return processing times in seconds for completed jobs."""
    times: list[float] = []
    for j in jobs:
        started = j.get("started_at")
        completed = j.get("completed_at")
        if started and completed:
            t0 = datetime.fromisoformat(started)
            t1 = datetime.fromisoformat(completed)
            diff = (t1 - t0).total_seconds()
            if diff >= 0:
                times.append(diff)
    return times


def _bucket_processing_times(times: list[float]) -> dict[str, int]:
    """Bucket processing times into histogram bins."""
    buckets = {"0-5s": 0, "5-15s": 0, "15-30s": 0, "30-60s": 0, "60s+": 0}
    for t in times:
        if t <= 5:
            buckets["0-5s"] += 1
        elif t <= 15:
            buckets["5-15s"] += 1
        elif t <= 30:
            buckets["15-30s"] += 1
        elif t <= 60:
            buckets["30-60s"] += 1
        else:
            buckets["60s+"] += 1
    return buckets


def _aggregate_daily_volume(jobs: list[dict], days: int = 30) -> dict[str, int]:
    """Count jobs per day for the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    counts: Counter[str] = Counter()
    for j in jobs:
        created = j.get("created_at")
        if not created:
            continue
        dt = datetime.fromisoformat(created)
        if dt >= cutoff:
            counts[dt.strftime("%Y-%m-%d")] += 1

    # Fill in missing days with zero
    result: dict[str, int] = {}
    for i in range(days):
        day = (cutoff + timedelta(days=i + 1)).strftime("%Y-%m-%d")
        result[day] = counts.get(day, 0)
    return result


def render() -> None:
    st.title("Dashboard")

    auto_refresh = st.sidebar.checkbox("Auto-refresh (30s)", value=False)

    try:
        stats = api.get_stats()

        # Top metrics
        _metrics = [
            ("Total Documents", stats.get("total_documents", 0)),
            ("Total Jobs", stats.get("total_jobs", 0)),
            ("Success Rate", f"{stats.get('success_rate', 0):.1f}%"),
            ("Avg Processing", f"{stats.get('avg_processing_time_ms', 0) / 1000:.1f}s"),
            ("Needs Review", stats.get("needs_review", 0)),
            ("Avg Confidence", f"{stats.get('avg_confidence_score', 0):.1%}"),
        ]
        cols = st.columns(len(_metrics))
        for i, (label, value) in enumerate(_metrics):
            with cols[i]:
                if _HAS_EXTRAS:
                    with _stylable(key=f"kpi_{i}", css_styles=_METRIC_CSS):
                        st.metric(label, value)
                else:
                    st.metric(label, value)

        st.divider()

        # Charts row 1 — existing
        col1, col2 = st.columns(2)

        with col1:
            # Document type breakdown
            type_data = stats.get("doc_type_breakdown", {})
            if type_data:
                fig = px.pie(
                    values=list(type_data.values()),
                    names=[k.replace("_", " ").title() for k in type_data.keys()],
                    title="Document Type Distribution",
                    template="plotly_dark",
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No document type data yet")

        with col2:
            # Job status breakdown
            completed = stats.get("completed_jobs", 0)
            failed = stats.get("failed_jobs", 0)
            total = stats.get("total_jobs", 0)
            in_progress = total - completed - failed

            if total > 0:
                fig = go.Figure(go.Bar(
                    x=["Completed", "Failed", "In Progress"],
                    y=[completed, failed, max(0, in_progress)],
                    marker_color=["#2ecc71", "#e74c3c", "#3498db"],
                ))
                fig.update_layout(title="Job Status Overview", **PLOTLY_DARK)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No job data yet")

        st.divider()

        # Fetch jobs for the new charts
        jobs = api.list_jobs(page=1, page_size=100)

        # Charts row 2 — new
        col3, col4 = st.columns(2)

        with col3:
            st.subheader("Processing Time Distribution")
            proc_times = _compute_processing_times(jobs)
            if proc_times:
                buckets = _bucket_processing_times(proc_times)
                fig = go.Figure(go.Bar(
                    x=list(buckets.keys()),
                    y=list(buckets.values()),
                    marker_color="#9b59b6",
                ))
                fig.update_layout(
                    xaxis_title="Duration",
                    yaxis_title="Jobs",
                    **PLOTLY_DARK,
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No processing time data yet")

        with col4:
            st.subheader("Daily Processing Volume (30 days)")
            daily = _aggregate_daily_volume(jobs, days=30)
            if any(v > 0 for v in daily.values()):
                fig = go.Figure(go.Scatter(
                    x=list(daily.keys()),
                    y=list(daily.values()),
                    mode="lines+markers",
                    line=dict(color="#3498db"),
                ))
                fig.update_layout(
                    xaxis_title="Date",
                    yaxis_title="Jobs Submitted",
                    **PLOTLY_DARK,
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No data yet")

        # Auto-refresh
        if auto_refresh:
            time.sleep(2)
            st.rerun()

    except Exception as e:
        st.error(f"Could not load statistics: {e}")
        st.info("Make sure the API is running and your API key is configured.")
