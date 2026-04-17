"""Quality Monitor — LLM-judge quality trend dashboard."""
from __future__ import annotations

import os
import random
from datetime import date, timedelta

import plotly.graph_objects as go
import streamlit as st

from frontend.theme import PLOTLY_DARK

DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")

DIM_LABELS = {
    "completeness": "Completeness",
    "field_accuracy": "Field Accuracy",
    "hallucination_absence": "Hallucination Absence",
    "format_compliance": "Format Compliance",
}
DIM_COLORS = {
    "completeness": "#3498db",
    "field_accuracy": "#2ecc71",
    "hallucination_absence": "#e74c3c",
    "format_compliance": "#9b59b6",
}


# ---------------------------------------------------------------------------
# Demo data helpers
# ---------------------------------------------------------------------------

def _demo_trend(days: int = 30) -> dict:
    """Generate synthetic 30-day quality trend data."""
    random.seed(42)
    today = date.today()
    dates = [(today - timedelta(days=days - i)).isoformat() for i in range(days)]

    alpha = 0.3
    ewma_val = 0.82
    ewma_composite = []
    for d in dates:
        jitter = random.uniform(-0.03, 0.03)
        ewma_val = alpha * max(0.70, min(0.98, ewma_val + jitter)) + (1 - alpha) * ewma_val
        ewma_composite.append({"date": d, "score": round(ewma_val, 4)})

    per_dimension: dict[str, list[dict]] = {}
    dim_bases = {
        "completeness": 0.88,
        "field_accuracy": 0.85,
        "hallucination_absence": 0.92,
        "format_compliance": 0.90,
    }
    for dim, base in dim_bases.items():
        series = []
        val = base
        for d in dates:
            val = alpha * max(0.70, min(0.99, val + random.uniform(-0.02, 0.02))) + (1 - alpha) * val
            series.append({"date": d, "score": round(val, 4)})
        per_dimension[dim] = series

    last_score = ewma_composite[-1]["score"] if ewma_composite else 0.0
    avg_7d = sum(p["score"] for p in ewma_composite[-7:]) / min(7, len(ewma_composite))

    return {
        "days": days,
        "ewma_composite": ewma_composite,
        "per_dimension": per_dimension,
        "escalation_rate": 0.12,
        "sample_count": days * random.randint(8, 15),
        "_last_score": last_score,
        "_avg_7d": avg_7d,
    }


# ---------------------------------------------------------------------------
# API fetch
# ---------------------------------------------------------------------------

def _fetch_trend(days: int) -> dict | None:
    try:
        import httpx
        api_url = os.environ.get("API_URL", "http://localhost:8000")
        api_key = os.environ.get("API_KEY", "")
        resp = httpx.get(
            f"{api_url}/api/v1/metrics/quality-trend",
            params={"days": days},
            headers={"X-API-Key": api_key},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            scores = [p["score"] for p in data.get("ewma_composite", [])]
            data["_last_score"] = scores[-1] if scores else 0.0
            data["_avg_7d"] = sum(scores[-7:]) / min(7, len(scores)) if scores else 0.0
            return data
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render() -> None:
    st.title("Quality Monitor")
    st.caption("LLM-judge evaluation scores — 4-dimension rubric, EWMA smoothed.")

    if DEMO_MODE:
        st.info("Demo data — synthetic 30-day quality trend", icon="🔬")

    days = st.slider("Window (days)", min_value=7, max_value=90, value=30, step=7)

    # Load data
    data: dict | None = None
    using_demo = False

    if not DEMO_MODE:
        data = _fetch_trend(days)

    if data is None:
        data = _demo_trend(days)
        using_demo = True
        if not DEMO_MODE:
            st.warning("API unavailable — showing demo data.")

    # ── KPI row ─────────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Composite (last day)", f"{data['_last_score']:.1%}")
    with col2:
        st.metric("Composite (7d avg)", f"{data['_avg_7d']:.1%}")
    with col3:
        st.metric("Sample Count", f"{data['sample_count']:,}")
    with col4:
        st.metric("HITL Escalation Rate", f"{data['escalation_rate']:.1%}")

    st.divider()

    # ── EWMA composite line chart ────────────────────────────────────────────
    st.subheader("Composite Quality Trend (EWMA α=0.3)")

    ewma_points = data.get("ewma_composite", [])
    if ewma_points:
        dates = [p["date"] for p in ewma_points]
        scores = [p["score"] for p in ewma_points]

        fig_line = go.Figure()
        fig_line.add_trace(
            go.Scatter(
                x=dates,
                y=scores,
                mode="lines+markers",
                name="Composite EWMA",
                line=dict(color="#3498db", width=2),
                marker=dict(size=4),
                fill="tozeroy",
                fillcolor="rgba(52,152,219,0.1)",
            )
        )
        fig_line.add_hline(
            y=0.80,
            line_dash="dash",
            line_color="rgba(255,255,255,0.3)",
            annotation_text="80% target",
            annotation_position="bottom right",
        )
        fig_line.update_layout(
            yaxis=dict(title="Score (0–1)", range=[0.5, 1.0]),
            xaxis_title="Date",
            height=320,
            margin=dict(t=20, b=20),
            **PLOTLY_DARK,
        )
        st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.info("No quality data in this window. Process some documents to populate scores.")

    st.divider()

    # ── Per-dimension bar chart (latest day avg) ─────────────────────────────
    st.subheader("Per-Dimension Scores (latest day)")

    per_dim = data.get("per_dimension", {})
    dim_names = list(DIM_LABELS.keys())
    dim_scores = [per_dim[d][-1]["score"] if per_dim.get(d) else 0.0 for d in dim_names]
    dim_labels = [DIM_LABELS[d] for d in dim_names]
    dim_colors = [DIM_COLORS[d] for d in dim_names]

    fig_bar = go.Figure(
        go.Bar(
            x=dim_labels,
            y=dim_scores,
            marker_color=dim_colors,
            text=[f"{s:.1%}" for s in dim_scores],
            textposition="outside",
        )
    )
    fig_bar.update_layout(
        yaxis=dict(title="Score (0–1)", range=[0.0, 1.1]),
        xaxis_title="Dimension",
        height=320,
        margin=dict(t=20, b=20),
        **PLOTLY_DARK,
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    st.divider()

    # ── Per-dimension trend lines ────────────────────────────────────────────
    st.subheader("Per-Dimension Trends")

    if per_dim and any(per_dim.values()):
        fig_multi = go.Figure()
        for dim in dim_names:
            series = per_dim.get(dim, [])
            if series:
                fig_multi.add_trace(
                    go.Scatter(
                        x=[p["date"] for p in series],
                        y=[p["score"] for p in series],
                        mode="lines",
                        name=DIM_LABELS[dim],
                        line=dict(color=DIM_COLORS[dim], width=1.5),
                    )
                )
        fig_multi.update_layout(
            yaxis=dict(title="Score (0–1)", range=[0.5, 1.0]),
            xaxis_title="Date",
            height=320,
            margin=dict(t=20, b=20),
            legend=dict(orientation="h", yanchor="bottom", y=-0.35),
            **PLOTLY_DARK,
        )
        st.plotly_chart(fig_multi, use_container_width=True)

    if using_demo and not DEMO_MODE:
        st.caption("Showing demo data. Connect the API and run extraction jobs to see real scores.")


render()
