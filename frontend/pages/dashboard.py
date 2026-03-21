"""Screen 6: Analytics dashboard."""
from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import frontend.api_client as api


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
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        with col1:
            st.metric("Total Documents", stats.get("total_documents", 0))
        with col2:
            st.metric("Total Jobs", stats.get("total_jobs", 0))
        with col3:
            st.metric("Success Rate", f"{stats.get('success_rate', 0):.1f}%")
        with col4:
            avg_ms = stats.get("avg_processing_time_ms", 0)
            st.metric("Avg Processing Time", f"{avg_ms / 1000:.1f}s")
        with col5:
            st.metric("Needs Review", stats.get("needs_review", 0))
        with col6:
            avg_conf = stats.get("avg_confidence_score", 0)
            st.metric("Avg Confidence", f"{avg_conf:.1%}")

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
                fig.update_layout(title="Job Status Overview")
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
