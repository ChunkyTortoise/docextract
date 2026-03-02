"""Screen 4: Records browser with filtering."""
import streamlit as st
import pandas as pd
import frontend.api_client as api


DOCUMENT_TYPES = ["All", "Invoice", "Purchase Order", "Receipt", "Bank Statement", "Identity Document", "Medical Record"]


def render() -> None:
    st.title("Extracted Records")

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
        has_next = data.get("has_next", False)

        st.caption(f"Showing {len(items)} of {total} records")

        if items:
            df = pd.DataFrame(items)

            # Format for display
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

                col1, col2 = st.columns(2)
                with col1:
                    if st.button("View Results"):
                        st.rerun()
                with col2:
                    if st.button("Review"):
                        st.rerun()
        else:
            st.info("No records found matching your filters.")

        # Export
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Export CSV"):
                csv_data = api.export_records("csv")
                st.download_button("Download CSV", csv_data, "records.csv", "text/csv")
        with col2:
            if st.button("Export JSON"):
                json_data = api.export_records("json")
                st.download_button("Download JSON", json_data, "records.json", "application/json")

    except Exception as e:
        st.error(f"Could not load records: {e}")
