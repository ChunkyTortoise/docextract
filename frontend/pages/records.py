"""Screen 4: Records browser with filtering."""
import os

import pandas as pd
import streamlit as st

import frontend.api_client as api

DOCUMENT_TYPES = ["All", "Invoice", "Purchase Order", "Receipt", "Bank Statement", "Identity Document", "Medical Record"]


def _render_records_table(items: list[dict]) -> None:
    """Render a records table with row selection."""
    demo_mode = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")
    df = pd.DataFrame(items)
    display_cols = ["id", "document_type", "confidence_score", "needs_review", "review_status", "created_at"]
    display_df = df[[c for c in display_cols if c in df.columns]]

    selected = st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )

    if selected and selected.selection.rows:
        row_idx = selected.selection.rows[0]
        record_id = items[row_idx]["id"]
        st.session_state["current_record_id"] = record_id
        st.info(f"Selected record: `{record_id[:8]}...`")

        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("View Results"):
                st.session_state["current_job_id"] = items[row_idx].get("job_id")
                st.session_state["nav_target"] = "Results"
                st.rerun()
        with col2:
            if st.button("Review"):
                st.session_state["nav_target"] = "Review"
                st.rerun()
        with col3:
            if not demo_mode:
                if st.button("Delete", type="secondary"):
                    st.session_state["confirm_delete"] = record_id

        if not demo_mode and st.session_state.get("confirm_delete") == record_id:
            st.warning("Are you sure? This cannot be undone.")
            col_yes, col_no = st.columns(2)
            with col_yes:
                if st.button("Confirm Delete"):
                    try:
                        api.delete_document(items[row_idx].get("document_id"))
                        st.session_state["confirm_delete"] = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Delete failed: {e}")
            with col_no:
                if st.button("Cancel"):
                    st.session_state["confirm_delete"] = None
                    st.rerun()


def render() -> None:
    st.title("Extracted Records")

    # Semantic search
    search_query = st.text_input("Search records", placeholder="e.g. invoice total, contract date...")
    if search_query:
        try:
            results = api.search_records(search_query, limit=10)
            items = [r["record"] for r in results] if isinstance(results, list) else results.get("items", [])
            if items:
                st.caption(f"Found {len(items)} results for \"{search_query}\"")
                _render_records_table(items)
            else:
                st.info("No records matched your search.")
        except Exception as e:
            st.error(f"Search failed: {e}")
        return

    # Filters sidebar
    with st.sidebar:
        st.subheader("Filters")
        doc_type_filter = st.selectbox("Document Type", DOCUMENT_TYPES, index=0)
        needs_review_filter = st.selectbox("Review Status", ["All", "Needs Review", "Reviewed"], index=0)
        min_confidence = st.slider("Min Confidence", 0.0, 1.0, 0.0, step=0.05)
        page = st.number_input("Page", min_value=1, value=1, step=1)

    try:
        # Build filter params
        params = {}
        if doc_type_filter != "All":
            params["document_type"] = doc_type_filter.lower().replace(" ", "_")
        if needs_review_filter == "Needs Review":
            params["needs_review"] = True
        elif needs_review_filter == "Reviewed":
            params["needs_review"] = False
        if min_confidence > 0:
            params["min_confidence"] = min_confidence

        data = api.get_records(page=page, page_size=20, **params)

        items = data.get("items", [])
        total = data.get("total", 0)
        has_next = data.get("has_next", False)  # noqa: F841

        st.caption(f"Showing {len(items)} of {total} records")

        if items:
            _render_records_table(items)
        else:
            st.info("No records found matching your filters.")

        # Export
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            csv_data = api.export_records("csv")
            st.download_button("Export CSV", csv_data, "records.csv", "text/csv")
        with col2:
            json_data = api.export_records("json")
            st.download_button("Export JSON", json_data, "records.json", "application/json")

    except Exception as e:
        st.error(f"Could not load records: {e}")
