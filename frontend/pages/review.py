"""Screen 5: Human review interface."""
import os

import streamlit as st
import frontend.api_client as api


def render() -> None:
    st.title("Document Review")

    demo_mode = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")

    record_id = st.session_state.get("current_record_id")
    if not record_id:
        record_id = st.text_input("Enter Record ID to review")
        if not record_id:
            st.info("No record selected. Browse records and click 'Review'.")
            return

    st.caption(f"Record ID: `{record_id}`")

    try:
        record = api.get_record(record_id)

        # Show metadata
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Document Type", record.get("document_type", "Unknown").replace("_", " ").title())
        with col2:
            conf = record.get("confidence_score", 0)
            st.metric("Confidence", f"{conf:.1%}")
        with col3:
            st.metric("Status", record.get("review_status") or "Pending")

        # Editable form
        st.subheader("Edit Extracted Data")

        extracted = record.get("extracted_data") or {}
        corrected = record.get("corrected_data") or {}
        current_data = {**extracted, **corrected}

        corrections = {}
        for key, value in current_data.items():
            if key.startswith("_") or isinstance(value, (list, dict)):
                continue
            new_value = st.text_input(
                key.replace("_", " ").title(),
                value=str(value) if value is not None else "",
                key=f"field_{key}",
            )
            if new_value != str(value or ""):
                corrections[key] = new_value

        reviewer_notes = st.text_area("Reviewer Notes")

        # Actions
        st.divider()
        if demo_mode:
            st.info("Review actions are disabled in demo mode.")
            return
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Approve", type="primary"):
                with st.spinner("Submitting review..."):
                    try:
                        api.review_record(
                            record_id=record_id,
                            decision="approve",
                            corrections=corrections if corrections else None,
                            reviewer_notes=reviewer_notes or None,
                        )
                        st.success("Record approved!")
                        st.session_state["current_record_id"] = None
                    except Exception as e:
                        st.error(f"Review failed: {e}")

        with col2:
            if st.button("Reject", type="secondary"):
                with st.spinner("Submitting review..."):
                    try:
                        api.review_record(
                            record_id=record_id,
                            decision="reject",
                            corrections=corrections if corrections else None,
                            reviewer_notes=reviewer_notes or None,
                        )
                        st.warning("Record rejected.")
                        st.session_state["current_record_id"] = None
                    except Exception as e:
                        st.error(f"Review failed: {e}")

    except Exception as e:
        st.error(f"Could not load record: {e}")
