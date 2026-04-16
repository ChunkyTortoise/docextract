"""Screen 2: Job progress tracking."""
import time

import streamlit as st

import frontend.api_client as api
from frontend.components.progress_bar import display_progress

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def render() -> None:
    st.title("Processing Progress")

    job_id = st.session_state.get("current_job_id")

    if not job_id:
        job_id = st.text_input("Enter Job ID to track")
        if not job_id:
            st.info("No job selected. Upload a document first or enter a Job ID.")
            return

    st.caption(f"Job ID: `{job_id}`")

    auto_refresh = st.checkbox("Auto-refresh (every 2s)", value=True)

    try:
        job = api.get_job(job_id)
        display_progress(job)

        status = job.get("status", "")

        if status not in TERMINAL_STATUSES:
            if st.button("Cancel Job"):
                try:
                    api.cancel_job(job_id)
                    st.warning("Job cancelled.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Cancel failed: {e}")

        if status == "completed":
            st.success("Document processing complete!")
            if st.button("View Results"):
                st.session_state["current_job_id"] = job_id
                st.rerun()
        elif status == "failed":
            st.error(f"Processing failed: {job.get('error_message', 'Unknown error')}")
            if st.button("Retry (upload again)"):
                st.session_state["current_job_id"] = None
                st.rerun()
        elif auto_refresh and status not in TERMINAL_STATUSES:
            time.sleep(2)
            st.rerun()

    except Exception as e:
        st.error(f"Could not load job: {e}")
