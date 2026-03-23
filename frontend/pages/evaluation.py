"""Evaluation Dashboard — RAGAS and LLM-judge metrics over time."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st
import plotly.graph_objects as go
from frontend.theme import PLOTLY_DARK

# ---------------------------------------------------------------------------
# Mock data helpers (used when no real eval data is available)
# ---------------------------------------------------------------------------

_METRICS = ["context_recall", "faithfulness", "answer_relevancy", "llm_judge"]

_METRIC_COLORS = {
    "context_recall": "#3498db",
    "faithfulness": "#2ecc71",
    "answer_relevancy": "#e67e22",
    "llm_judge": "#9b59b6",
}


def _generate_mock_runs(n: int = 10) -> list[dict]:
    """Return N mock eval run rows for demo purposes."""
    import random

    random.seed(42)
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(n):
        run_ts = now - timedelta(days=n - i - 1)
        for metric in _METRICS:
            base = {"context_recall": 0.82, "faithfulness": 0.88, "answer_relevancy": 0.79, "llm_judge": 0.85}[metric]
            score = round(min(1.0, max(0.0, base + random.uniform(-0.08, 0.08))), 3)
            rows.append(
                {
                    "run_id": f"run-{i:03d}",
                    "fixture_name": f"invoice_{(i % 4) + 1:02d}",
                    "metric_name": metric,
                    "score": score,
                    "passed": score >= 0.7,
                    "threshold": 0.7,
                    "created_at": run_ts.isoformat(),
                }
            )
    return rows


def _latest_scores_by_metric(rows: list[dict]) -> dict[str, float | None]:
    """Return the most recent score per metric."""
    latest: dict[str, float | None] = {m: None for m in _METRICS}
    for row in sorted(rows, key=lambda r: r["created_at"], reverse=True):
        m = row["metric_name"]
        if latest[m] is None:
            latest[m] = row["score"]
    return latest


def _previous_scores_by_metric(rows: list[dict]) -> dict[str, float | None]:
    """Return the second-most-recent score per metric."""
    seen: dict[str, int] = {m: 0 for m in _METRICS}
    prev: dict[str, float | None] = {m: None for m in _METRICS}
    for row in sorted(rows, key=lambda r: r["created_at"], reverse=True):
        m = row["metric_name"]
        seen[m] += 1
        if seen[m] == 2:
            prev[m] = row["score"]
    return prev


def _build_time_series(rows: list[dict]) -> dict[str, tuple[list[str], list[float]]]:
    """Return {metric: (dates, scores)} sorted by date ascending."""
    series: dict[str, list[tuple[str, float]]] = {m: [] for m in _METRICS}
    for row in rows:
        m = row["metric_name"]
        ts = row["created_at"][:10]  # YYYY-MM-DD
        series[m].append((ts, row["score"]))

    result: dict[str, tuple[list[str], list[float]]] = {}
    for m, pts in series.items():
        pts_sorted = sorted(pts, key=lambda x: x[0])
        if pts_sorted:
            dates, scores = zip(*pts_sorted)
            result[m] = (list(dates), list(scores))
        else:
            result[m] = ([], [])
    return result


def _last_10_runs_table(rows: list[dict]) -> list[dict]:
    """Return rows for the last 10 unique run_ids, one row per fixture per metric."""
    run_ids: list[str] = []
    seen: set[str] = set()
    for row in sorted(rows, key=lambda r: r["created_at"], reverse=True):
        rid = row["run_id"]
        if rid not in seen:
            run_ids.append(rid)
            seen.add(rid)
        if len(run_ids) == 10:
            break

    run_id_set = set(run_ids)
    return [r for r in rows if r["run_id"] in run_id_set]


def _check_regression(
    latest: dict[str, float | None],
    previous: dict[str, float | None],
    tolerance: float = 0.05,
) -> list[str]:
    """Return list of metrics that regressed beyond tolerance."""
    regressions: list[str] = []
    for m in _METRICS:
        l_score = latest.get(m)
        p_score = previous.get(m)
        if l_score is not None and p_score is not None:
            if l_score < (p_score - tolerance):
                regressions.append(
                    f"{m}: {p_score:.3f} → {l_score:.3f} (dropped {p_score - l_score:.3f})"
                )
    return regressions


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------


def render() -> None:
    st.title("Evaluation Dashboard")

    st.caption(
        "RAGAS-inspired metrics (context recall, faithfulness, answer relevancy) "
        "and LLM-as-judge scores over time. "
        "Enable live data by setting RAGAS_ENABLED=true and LLM_JUDGE_ENABLED=true."
    )

    # Try to load real eval history from the API; fall back to mock data
    rows: list[dict] = []
    using_mock = False
    try:
        import frontend.api_client as api  # noqa: PLC0415
        rows = api.get_eval_history(limit=200)
    except Exception:
        rows = []

    if not rows:
        using_mock = True
        rows = _generate_mock_runs(10)
        st.info(
            "No live eval history found — showing mock data. "
            "Run the RAGAS eval pipeline to populate real results."
        )

    # ── Regression alert ─────────────────────────────────────────────────
    latest_scores = _latest_scores_by_metric(rows)
    prev_scores = _previous_scores_by_metric(rows)
    regressions = _check_regression(latest_scores, prev_scores)

    if regressions:
        st.error("**Regression detected (>0.05 drop from previous run):**\n\n" + "\n\n".join(f"- {r}" for r in regressions))
    else:
        st.success("No regressions detected since last run.")

    st.divider()

    # ── KPI cards for latest scores ──────────────────────────────────────
    cols = st.columns(len(_METRICS))
    for col, metric in zip(cols, _METRICS):
        score = latest_scores.get(metric)
        label = metric.replace("_", " ").title()
        with col:
            if score is not None:
                delta: str | None = None
                prev = prev_scores.get(metric)
                if prev is not None:
                    delta = f"{score - prev:+.3f}"
                st.metric(label, f"{score:.3f}", delta=delta)
            else:
                st.metric(label, "N/A")

    st.divider()

    # ── Line chart: scores over time per metric ──────────────────────────
    st.subheader("Scores Over Time")
    time_series = _build_time_series(rows)

    fig = go.Figure()
    for metric in _METRICS:
        dates, scores = time_series.get(metric, ([], []))
        if dates:
            fig.add_trace(
                go.Scatter(
                    x=dates,
                    y=scores,
                    mode="lines+markers",
                    name=metric.replace("_", " ").title(),
                    line=dict(color=_METRIC_COLORS[metric]),
                )
            )

    fig.add_hline(
        y=0.7,
        line_dash="dash",
        line_color="red",
        annotation_text="Pass threshold (0.70)",
        annotation_position="bottom right",
    )
    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Score",
        yaxis=dict(range=[0, 1.05]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        height=400,
        **PLOTLY_DARK,
    )
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Last 10 runs table ───────────────────────────────────────────────
    st.subheader("Last 10 Eval Runs")

    table_rows = _last_10_runs_table(rows)
    if table_rows:
        # Build a pivot: run_id × fixture → {metric: pass/fail}
        pivot: dict[str, dict] = {}
        for row in table_rows:
            key = f"{row['run_id']} / {row['fixture_name']}"
            if key not in pivot:
                pivot[key] = {"run": row["run_id"], "fixture": row["fixture_name"], "date": row["created_at"][:10]}
            pivot[key][row["metric_name"]] = ("PASS" if row["passed"] else "FAIL", row["score"])

        table_data = []
        for _key, rec in pivot.items():
            entry: dict = {
                "Run": rec["run"],
                "Fixture": rec["fixture"],
                "Date": rec["date"],
            }
            for m in _METRICS:
                label = m.replace("_", " ").title()
                val = rec.get(m)
                if val:
                    status, score = val
                    entry[label] = f"{status} ({score:.3f})"
                else:
                    entry[label] = "—"
            table_data.append(entry)

        st.dataframe(
            table_data,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No run data to display.")

    if using_mock:
        st.caption("Displaying mock data. Set RAGAS_ENABLED=true to collect real metrics.")
