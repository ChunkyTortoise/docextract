"""ROI dashboard page."""
from __future__ import annotations

import os
from datetime import date, timedelta

import streamlit as st
import plotly.graph_objects as go
import frontend.api_client as api


def render() -> None:
    st.title("ROI Dashboard")

    demo_mode = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")

    # Date range selector
    col_from, col_to, col_interval = st.columns(3)
    with col_from:
        date_from = st.date_input("From", value=date.today() - timedelta(days=30))
    with col_to:
        date_to = st.date_input("To", value=date.today())
    with col_interval:
        interval = st.selectbox("Interval", ["week", "month"], index=0)

    date_from_str = date_from.isoformat() if date_from else None
    date_to_str = date_to.isoformat() if date_to else None

    try:
        summary = api.get_roi_summary(date_from=date_from_str, date_to=date_to_str)

        # KPI cards
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Jobs Completed", summary.get("jobs_completed", 0))
        with col2:
            avg_conf = summary.get("avg_confidence", 0)
            st.metric("Avg Confidence", f"{avg_conf:.1%}")
        with col3:
            minutes_saved = summary.get("minutes_saved", 0)
            st.metric("Minutes Saved", f"{minutes_saved:,.0f}")
        with col4:
            dollars_saved = summary.get("dollars_saved", 0)
            st.metric("Dollars Saved", f"${dollars_saved:,.2f}")
        with col5:
            net_value = summary.get("net_value", 0)
            st.metric("Net Value", f"${net_value:,.2f}")

        st.divider()

        # Trend charts
        try:
            trends = api.get_roi_trends(
                interval=interval,
                date_from=date_from_str,
                date_to=date_to_str,
            )
            trend_items = trends.get("items", [])

            col_left, col_right = st.columns(2)

            with col_left:
                st.subheader("Dollars Saved Over Time")
                if trend_items:
                    fig = go.Figure(go.Scatter(
                        x=[t.get("period") for t in trend_items],
                        y=[t.get("dollars_saved", 0) for t in trend_items],
                        mode="lines+markers",
                        line=dict(color="#2ecc71"),
                    ))
                    fig.update_layout(xaxis_title="Period", yaxis_title="Dollars Saved ($)")
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No trend data available for this period.")

            with col_right:
                st.subheader("Net Value Over Time")
                if trend_items:
                    fig = go.Figure(go.Scatter(
                        x=[t.get("period") for t in trend_items],
                        y=[t.get("net_value", 0) for t in trend_items],
                        mode="lines+markers",
                        line=dict(color="#3498db"),
                    ))
                    fig.update_layout(xaxis_title="Period", yaxis_title="Net Value ($)")
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No trend data available for this period.")

        except Exception as e:
            st.warning(f"Could not load trend data: {e}")

    except Exception as e:
        st.error(f"Could not load ROI summary: {e}")

    st.divider()

    # Report section
    st.subheader("Reports")

    if not demo_mode:
        with st.expander("Generate New Report"):
            fmt = st.selectbox("Format", ["both", "json", "html"], index=0)
            if st.button("Generate Report", type="primary"):
                with st.spinner("Generating report..."):
                    try:
                        result = api.generate_report(
                            date_from=date_from_str,
                            date_to=date_to_str,
                            format=fmt,
                        )
                        st.success(f"Report generated: {result.get('report_id', '')}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Report generation failed: {e}")
    else:
        st.info("Report generation is disabled in demo mode.")

    # Past reports table
    try:
        reports_data = api.list_reports(limit=20)
        report_items = reports_data.get("items", reports_data) if isinstance(reports_data, dict) else reports_data
        if report_items:
            st.caption(f"{len(report_items)} report(s) available")
            for r in report_items:
                report_id = r.get("report_id") or r.get("id", "")
                created = r.get("created_at", "")
                fmt = r.get("format", "")
                with st.expander(f"Report {report_id[:8]}... — {created[:10]} ({fmt})"):
                    st.json(r)
        else:
            st.info("No reports generated yet.")
    except Exception as e:
        st.warning(f"Could not load reports: {e}")
