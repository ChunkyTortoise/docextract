"""Screen 6: Analytics dashboard."""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import frontend.api_client as api


def render() -> None:
    st.title("Dashboard")

    auto_refresh = st.sidebar.checkbox("Auto-refresh (30s)", value=False)

    try:
        stats = api.get_stats()

        # Top metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Documents", stats.get("total_documents", 0))
        with col2:
            st.metric("Total Jobs", stats.get("total_jobs", 0))
        with col3:
            st.metric("Success Rate", f"{stats.get('success_rate', 0):.1f}%")
        with col4:
            avg_ms = stats.get("avg_processing_time_ms", 0)
            st.metric("Avg Processing Time", f"{avg_ms / 1000:.1f}s")

        st.divider()

        # Charts
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

        # Auto-refresh
        if auto_refresh:
            import time
            time.sleep(30)
            st.rerun()

    except Exception as e:
        st.error(f"Could not load statistics: {e}")
        st.info("Make sure the API is running and your API key is configured.")
