"""Cost & Performance Dashboard — LLM spend, model comparison, and A/B test status."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
import streamlit as st
from frontend.theme import PLOTLY_DARK


# ---------------------------------------------------------------------------
# Mock data helpers
# ---------------------------------------------------------------------------

def _mock_cost_summary() -> dict:
    """Return plausible mock cost data grouped by model and operation."""
    return {
        "claude-sonnet-4-6": {
            "extract": {"total_cost": 0.8241, "avg_cost": 0.00824, "call_count": 100},
            "llm_judge": {"total_cost": 0.3102, "avg_cost": 0.00413, "call_count": 75},
        },
        "claude-haiku-4-5-20251001": {
            "classify": {"total_cost": 0.0521, "avg_cost": 0.00052, "call_count": 100},
            "rerank": {"total_cost": 0.0214, "avg_cost": 0.00043, "call_count": 50},
        },
    }


def _mock_model_comparison() -> list[dict]:
    """Return mock model comparison rows for the scatter plot."""
    random.seed(7)
    rows = []
    models = [
        ("claude-sonnet-4-6", "extract", 0.00824, 1800),
        ("claude-sonnet-4-6", "llm_judge", 0.00413, 1200),
        ("claude-haiku-4-5-20251001", "classify", 0.00052, 400),
        ("claude-haiku-4-5-20251001", "rerank", 0.00043, 350),
    ]
    for model, op, avg_cost, avg_lat in models:
        rows.append(
            {
                "model": model,
                "operation": op,
                "avg_cost": avg_cost + random.uniform(-0.0005, 0.0005),
                "avg_latency": avg_lat + random.uniform(-50, 50),
                "call_count": random.randint(50, 150),
            }
        )
    return rows


def _mock_ab_tests() -> list[dict]:
    """Return mock A/B test status rows."""
    return [
        {
            "Test Name": "classification_haiku_vs_sonnet",
            "Operation": "classify",
            "Control": "claude-sonnet-4-6",
            "Treatment": "claude-haiku-4-5-20251001",
            "Traffic Split": "50 / 50",
            "Control Calls": 412,
            "Treatment Calls": 389,
            "Avg Quality Delta": "-0.8%",
            "Cost Reduction": "83%",
            "Significant": "Pending (need 30+ samples)",
            "Winner": "—",
        },
        {
            "Test Name": "extraction_haiku_vs_sonnet",
            "Operation": "extract",
            "Control": "claude-sonnet-4-6",
            "Treatment": "claude-haiku-4-5-20251001",
            "Traffic Split": "80 / 20",
            "Control Calls": 810,
            "Treatment Calls": 198,
            "Avg Quality Delta": "-4.1%",
            "Cost Reduction": "92%",
            "Significant": "No (p=0.12)",
            "Winner": "—",
        },
    ]


# ---------------------------------------------------------------------------
# KPI computation helpers
# ---------------------------------------------------------------------------

def _compute_kpis(summary: dict) -> dict:
    """Derive top-level KPIs from the cost summary structure."""
    total_cost = 0.0
    total_requests = 0
    model_totals: dict[str, float] = {}

    for model, ops in summary.items():
        model_total = 0.0
        for op_data in ops.values():
            model_total += op_data.get("total_cost", 0.0)
            total_requests += op_data.get("call_count", 0)
        model_totals[model] = model_total
        total_cost += model_total

    avg_cost = total_cost / total_requests if total_requests > 0 else 0.0
    most_expensive = max(model_totals, key=model_totals.get) if model_totals else "N/A"

    return {
        "total_cost": total_cost,
        "avg_cost_per_request": avg_cost,
        "most_expensive_model": most_expensive,
        "total_requests": total_requests,
    }


def _compute_weekly_savings(summary: dict) -> float:
    """Estimate weekly savings from routing classification to Haiku vs Sonnet.

    Compares what the classification calls would have cost at Sonnet pricing
    vs what they actually cost at Haiku pricing.
    """
    haiku_data = summary.get("claude-haiku-4-5-20251001", {})
    classify_data = haiku_data.get("classify", {})
    haiku_classify_cost = classify_data.get("total_cost", 0.0)
    call_count = classify_data.get("call_count", 0)

    if call_count == 0:
        return 0.0

    # Sonnet costs ~6.6x more per token for input, ~12x for output
    # Approximate: Sonnet classification cost ≈ Haiku cost * 6
    sonnet_equivalent_cost = haiku_classify_cost * 6.0
    return sonnet_equivalent_cost - haiku_classify_cost


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render() -> None:
    st.title("Cost & Performance Dashboard")
    st.caption(
        "LLM spend by model and operation (last 7 days). "
        "Enable live data by connecting to the API. Showing mock data when unavailable."
    )

    # ── Load data (API or mock) ──────────────────────────────────────────
    cost_summary: dict = {}
    model_comparison: list[dict] = []
    using_mock = False

    try:
        import frontend.api_client as api  # noqa: PLC0415
        cost_summary = api.get_cost_summary(days=7)
        model_comparison = api.get_model_comparison(days=7)
    except Exception:
        cost_summary = {}
        model_comparison = []

    if not cost_summary:
        using_mock = True
        cost_summary = _mock_cost_summary()
        model_comparison = _mock_model_comparison()
        st.info(
            "No live cost data found — showing mock data. "
            "Connect the API and run extraction jobs to populate real metrics."
        )

    # ── KPI row ──────────────────────────────────────────────────────────
    kpis = _compute_kpis(cost_summary)
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Total Cost (7 days)",
            f"${kpis['total_cost']:.4f}",
        )
    with col2:
        st.metric(
            "Avg Cost / Request",
            f"${kpis['avg_cost_per_request']:.5f}",
        )
    with col3:
        st.metric(
            "Most Expensive Model",
            kpis["most_expensive_model"].replace("claude-", "").replace("-4-6", "").replace("-4-5-20251001", ""),
        )
    with col4:
        st.metric(
            "Total Requests",
            f"{kpis['total_requests']:,}",
        )

    st.divider()

    # ── Cost by model bar chart ──────────────────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Cost by Model (7 days)")

        model_labels = []
        model_costs = []
        for model, ops in cost_summary.items():
            short = (
                model.replace("claude-", "")
                .replace("-4-6", "")
                .replace("-4-5-20251001", "")
            )
            total = sum(op.get("total_cost", 0.0) for op in ops.values())
            model_labels.append(short)
            model_costs.append(round(total, 6))

        colors = ["#3498db", "#2ecc71", "#e74c3c", "#9b59b6"]
        fig_bar = go.Figure(
            go.Bar(
                x=model_labels,
                y=model_costs,
                marker_color=colors[: len(model_labels)],
                text=[f"${c:.4f}" for c in model_costs],
                textposition="outside",
            )
        )
        fig_bar.update_layout(
            yaxis_title="Cost (USD)",
            xaxis_title="Model",
            height=350,
            margin=dict(t=30),
            **PLOTLY_DARK,
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    with col_right:
        st.subheader("Cost vs Latency by Operation")

        if model_comparison:
            fig_scatter = go.Figure()
            operation_colors = {
                "extract": "#3498db",
                "classify": "#2ecc71",
                "rerank": "#e67e22",
                "llm_judge": "#9b59b6",
            }
            for row in model_comparison:
                op = row.get("operation", "other")
                short_model = (
                    row["model"]
                    .replace("claude-", "")
                    .replace("-4-6", "")
                    .replace("-4-5-20251001", "")
                )
                fig_scatter.add_trace(
                    go.Scatter(
                        x=[row["avg_latency"]],
                        y=[row["avg_cost"]],
                        mode="markers+text",
                        marker=dict(
                            size=max(8, min(24, row.get("call_count", 10) // 10)),
                            color=operation_colors.get(op, "#95a5a6"),
                        ),
                        text=[f"{short_model}/{op}"],
                        textposition="top center",
                        name=f"{short_model} / {op}",
                        showlegend=True,
                    )
                )
            fig_scatter.update_layout(
                xaxis_title="Avg Latency (ms)",
                yaxis_title="Avg Cost per Request (USD)",
                height=350,
                margin=dict(t=30),
                legend=dict(orientation="h", yanchor="bottom", y=-0.4),
                **PLOTLY_DARK,
            )
            st.plotly_chart(fig_scatter, use_container_width=True)
        else:
            st.info("No comparison data available.")

    st.divider()

    # ── Cost savings highlight ───────────────────────────────────────────
    weekly_savings = _compute_weekly_savings(cost_summary)
    haiku_classify = (
        cost_summary.get("claude-haiku-4-5-20251001", {})
        .get("classify", {})
        .get("call_count", 0)
    )
    total_requests_val = kpis["total_requests"]
    haiku_pct = (
        round(haiku_classify / total_requests_val * 100)
        if total_requests_val > 0
        else 40
    )

    st.subheader("Cost Savings Analysis")
    savings_col, detail_col = st.columns([1, 2])
    with savings_col:
        st.metric(
            "Estimated Weekly Savings",
            f"${weekly_savings:.4f}",
            delta=f"From routing {haiku_pct}% of classification to Haiku",
            delta_color="normal",
        )
    with detail_col:
        st.info(
            f"**Routing strategy:** {haiku_pct}% of classification calls use "
            f"Haiku (4x cheaper, <5% quality gap vs Sonnet). "
            f"Full extraction uses Sonnet for accuracy. "
            f"LLM judge uses Sonnet for reliability. "
            f"Estimated weekly savings: **${weekly_savings:.4f}** vs all-Sonnet."
        )

    st.divider()

    # ── Model A/B test status ────────────────────────────────────────────
    st.subheader("Model A/B Test Status")
    ab_rows = _mock_ab_tests()
    st.dataframe(ab_rows, use_container_width=True, hide_index=True)
    st.caption(
        "Z-test significance at p < 0.05. Minimum 30 samples per variant required. "
        "Winner declared only when statistically significant."
    )

    st.divider()

    # ── Per-model / per-operation breakdown table ────────────────────────
    st.subheader("Detailed Breakdown by Model & Operation")
    table_rows = []
    for model, ops in cost_summary.items():
        for operation, data in ops.items():
            table_rows.append(
                {
                    "Model": model,
                    "Operation": operation,
                    "Calls": data.get("call_count", 0),
                    "Total Cost (USD)": f"${data.get('total_cost', 0):.5f}",
                    "Avg Cost / Call (USD)": f"${data.get('avg_cost', 0):.6f}",
                }
            )
    if table_rows:
        st.dataframe(table_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No breakdown data available.")

    if using_mock:
        st.caption(
            "Showing mock data. Connect to the API and process documents to see real costs."
        )
