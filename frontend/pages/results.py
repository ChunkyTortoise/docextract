"""Screen 3: Extraction results viewer."""
import streamlit as st
import frontend.api_client as api
from frontend.components.json_viewer import display_extraction


def render() -> None:
    st.title("Extraction Results")

    job_id = st.session_state.get("current_job_id")
    if not job_id:
        st.info("No job selected. Upload a document or navigate from Progress page.")
        return

    try:
        # Get job to find record
        records = api.get_records(page_size=1)  # Get latest
        # In real impl: filter by job_id

        st.subheader("Extracted Data")

        if records.get("items"):
            record = records["items"][0]
            record_id = record["id"]

            # Load full record
            full_record = api.get_record(record_id)

            col1, col2 = st.columns([1, 1])

            with col1:
                st.subheader("Document Info")
                st.json({
                    "document_type": full_record.get("document_type"),
                    "confidence_score": full_record.get("confidence_score"),
                    "needs_review": full_record.get("needs_review"),
                })

            with col2:
                extracted_data = full_record.get("extracted_data") or {}
                display_extraction(extracted_data, title="Extracted Fields")

            # Actions
            st.divider()
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Download JSON"):
                    import json
                    st.download_button(
                        "Save JSON",
                        json.dumps(extracted_data, indent=2),
                        file_name=f"extraction_{record_id[:8]}.json",
                        mime="application/json",
                    )
            with col2:
                if full_record.get("needs_review"):
                    st.warning("This document needs human review")
                    st.session_state["current_record_id"] = record_id
                    if st.button("Go to Review"):
                        st.rerun()
        else:
            st.info("No records found. The job may still be processing.")

    except Exception as e:
        st.error(f"Could not load results: {e}")
