"""Batch upload page: upload multiple documents and track all jobs."""
import os
import time

import streamlit as st
import frontend.api_client as api
from frontend.components.progress_bar import display_progress


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

ACCEPTED_TYPES = ["pdf", "jpg", "jpeg", "png", "tiff", "tif", "eml", "msg"]


def render() -> None:
    st.title("Batch Upload")

    if os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes"):
        st.warning("Uploads are disabled in demo mode. This page is read-only.")
        return

    st.write("Upload multiple documents at once for parallel AI processing.")

    # --- Section A: Upload form ---
    with st.form("batch_upload_form"):
        files = st.file_uploader(
            "Choose files",
            type=ACCEPTED_TYPES,
            accept_multiple_files=True,
            help="Supported formats: PDF, JPG, PNG, TIFF, EML, MSG (max 50 MB)",
        )

        priority = st.selectbox("Priority", ["Normal", "High"], index=0)
        submitted = st.form_submit_button("Upload All", type="primary")

    if submitted and files:
        with st.spinner(f"Uploading {len(files)} file(s)..."):
            try:
                file_tuples = [
                    (f.name, f.read(), f.type or "application/octet-stream")
                    for f in files
                ]
                result = api.batch_upload(file_tuples, priority=priority.lower())

                job_ids: list[str] = result.get("job_ids", [])
                duplicates: list[str] = result.get("duplicates", [])

                # Map job_id -> filename using order of non-duplicate files
                dup_set = set(duplicates)
                non_dup_files = [f for f in files if f.name not in dup_set]
                filenames: dict[str, str] = {
                    jid: f.name
                    for jid, f in zip(job_ids, non_dup_files)
                }

                st.session_state["batch_job_ids"] = job_ids
                st.session_state["batch_filenames"] = filenames
                st.session_state["batch_duplicates"] = duplicates

                st.success(f"Submitted {len(job_ids)} job(s).")
                if duplicates:
                    st.info(f"Skipped duplicates: {', '.join(duplicates)}")

            except Exception as e:
                st.error(f"Batch upload failed: {e}")

    elif submitted:
        st.warning("Please select at least one file.")

    # --- Section B: Batch progress ---
    job_ids = st.session_state.get("batch_job_ids", [])
    filenames = st.session_state.get("batch_filenames", {})
    duplicates = st.session_state.get("batch_duplicates", [])

    if not job_ids:
        return

    st.divider()
    st.subheader("Batch Progress")

    if duplicates:
        st.caption(f"Duplicates skipped: {', '.join(duplicates)}")

    auto_refresh = st.checkbox("Auto-refresh (every 2s)", value=True)

    jobs: list[dict] = []
    for job_id in job_ids:
        try:
            jobs.append(api.get_job(job_id))
        except Exception as e:
            jobs.append({"job_id": job_id, "status": "failed", "error_message": str(e)})

    # Summary metrics
    total = len(jobs)
    completed = sum(1 for j in jobs if j.get("status") == "completed")
    processing = sum(1 for j in jobs if j.get("status") not in TERMINAL_STATUSES)
    failed = sum(1 for j in jobs if j.get("status") == "failed")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total", total)
    col2.metric("Completed", completed)
    col3.metric("Processing", processing)
    col4.metric("Failed", failed)

    demo_mode = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")

    # Per-job expanders
    for job in jobs:
        job_id = job.get("job_id", "unknown")
        filename = filenames.get(job_id, job_id)
        status = job.get("status", "unknown")
        with st.expander(f"{filename} — {status.title()}", expanded=(status not in TERMINAL_STATUSES)):
            st.caption(f"Job ID: `{job_id}`")
            display_progress(job)
            if status not in TERMINAL_STATUSES and not demo_mode:
                if st.button("Cancel", key=f"cancel_{job_id}"):
                    try:
                        api.cancel_job(job_id)
                        st.warning("Job cancelled.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Cancel failed: {e}")

    # Auto-refresh until all terminal
    all_done = all(j.get("status") in TERMINAL_STATUSES for j in jobs)

    if all_done:
        st.success("All jobs complete!")
        if st.button("View in Records"):
            st.session_state["batch_job_ids"] = []
            st.session_state["batch_filenames"] = {}
            st.session_state["batch_duplicates"] = []
            st.rerun()
    elif auto_refresh:
        time.sleep(2)
        st.rerun()
