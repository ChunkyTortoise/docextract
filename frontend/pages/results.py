"""Screen 3: Extraction results viewer."""
import json

import streamlit as st

import frontend.api_client as api
from frontend.components.json_viewer import display_extraction


@st.fragment
def _render_extraction_panel(full_record: dict) -> None:
    """Partial-rerun panel — updating this section won't reload the full page."""
    record_id = full_record["id"]

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Document Info")
        confidence = full_record.get("confidence_score", 0) or 0
        needs_review = full_record.get("needs_review", False)
        st.json({
            "document_type": full_record.get("document_type"),
            "confidence_score": confidence,
            "needs_review": needs_review,
        })

        # Confidence badge
        if confidence >= 0.9:
            st.success(f"High confidence: {confidence:.1%}")
        elif confidence >= 0.7:
            st.warning(f"Medium confidence: {confidence:.1%}")
        else:
            st.error(f"Low confidence: {confidence:.1%}")

    with col2:
        extracted_data = full_record.get("extracted_data") or {}
        display_extraction(extracted_data, title="Extracted Fields")

    # Actions
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "Download JSON",
            json.dumps(extracted_data, indent=2),
            file_name=f"extraction_{record_id[:8]}.json",
            mime="application/json",
        )
    with col2:
        if needs_review:
            st.warning("This document needs human review")
            st.session_state["current_record_id"] = record_id
            if st.button("Go to Review"):
                st.session_state["nav_target"] = "Review"
                st.rerun()


def render() -> None:
    st.title("Extraction Results")

    job_id = st.session_state.get("current_job_id")
    if not job_id:
        st.info("No job selected. Upload a document or navigate from Progress page.")
        return

    try:
        full_record = api.get_job_record(job_id)

        st.subheader("Extracted Data")

        if full_record:
            _render_extraction_panel(full_record)
        else:
            # Skeleton loading hint while job processes
            st.markdown(
                '<div class="skeleton" style="height:2rem;width:60%;margin-bottom:1rem"></div>'
                '<div class="skeleton" style="height:1.2rem;width:40%;margin-bottom:0.5rem"></div>'
                '<div class="skeleton" style="height:1.2rem;width:80%"></div>',
                unsafe_allow_html=True,
            )
            st.info("No records found. The job may still be processing.")

    except Exception as e:
        st.error(f"Could not load results: {e}")
