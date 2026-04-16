"""Job progress bar component with stage labels."""

import streamlit as st

STAGE_LABELS = {
    "queued": "Waiting in queue...",
    "processing": "Starting processing...",
    "extracting": "Extracting text...",
    "classifying": "Classifying document...",
    "validating": "Validating extracted data...",
    "embedding": "Creating search index...",
    "completed": "Processing complete!",
    "failed": "Processing failed",
    "cancelled": "Cancelled",
}

STATUS_PROGRESS = {
    "queued": 0,
    "processing": 5,
    "extracting": 20,
    "classifying": 40,
    "validating": 60,
    "embedding": 80,
    "completed": 100,
    "failed": -1,
    "cancelled": -1,
}


def display_progress(job: dict) -> None:
    """Display job progress with stage labels and progress bar.

    Args:
        job: Job dict from API with status, progress, created_at fields
    """
    status = job.get("status", "unknown")
    progress = job.get("progress", STATUS_PROGRESS.get(status, 0))
    label = STAGE_LABELS.get(status, f"Status: {status}")

    if status == "failed":
        st.error(f"Failed: {job.get('error_message', 'Unknown error')}")
        return

    if status == "cancelled":
        st.warning("Job cancelled")
        return

    # Progress bar (0-100 -> 0.0-1.0)
    pct = max(0, min(100, progress)) / 100
    st.progress(pct, text=label)

    # Stage metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Status", status.title())
    with col2:
        st.metric("Progress", f"{progress}%")
    with col3:
        if job.get("processing_time_ms"):
            st.metric("Time", f"{job['processing_time_ms'] / 1000:.1f}s")
        elif job.get("created_at"):
            st.metric("Priority", job.get("priority", "normal").title())
