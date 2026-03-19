"""Screen 1: Document upload."""
import os

import streamlit as st
import frontend.api_client as api


MIME_TYPES = {
    "application/pdf": "PDF",
    "image/jpeg": "JPEG Image",
    "image/png": "PNG Image",
    "image/tiff": "TIFF Image",
    "message/rfc822": "EML Email",
    "application/vnd.ms-outlook": "MSG Email",
}

DOCUMENT_TYPES = [
    "Auto-detect",
    "Invoice",
    "Purchase Order",
    "Receipt",
    "Bank Statement",
    "Identity Document",
    "Medical Record",
]


def render() -> None:
    st.title("Upload Document")

    if os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes"):
        st.warning("Uploads are disabled in demo mode. This page is read-only.")
        return

    st.write("Upload a document to extract structured data using AI.")

    with st.form("upload_form"):
        file = st.file_uploader(
            "Choose a file",
            type=["pdf", "jpg", "jpeg", "png", "tiff", "tif", "eml", "msg"],
            help="Supported formats: PDF, JPG, PNG, TIFF, EML, MSG",
        )

        col1, col2 = st.columns(2)
        with col1:
            doc_type = st.selectbox("Document Type", DOCUMENT_TYPES, index=0)
        with col2:
            priority = st.selectbox("Priority", ["Normal", "High"], index=0)

        webhook_url = st.text_input(
            "Webhook URL (optional)",
            placeholder="https://your-server.com/webhook",
        )

        submitted = st.form_submit_button("Upload and Process", type="primary")

    if submitted and file:
        with st.spinner("Uploading document..."):
            try:
                type_override = None if doc_type == "Auto-detect" else doc_type.lower().replace(" ", "_")
                result = api.upload_document(
                    file_bytes=file.read(),
                    filename=file.name,
                    mime_type=file.type or "application/octet-stream",
                    priority=priority.lower(),
                    document_type_override=type_override,
                )

                if result.get("duplicate"):
                    st.info(f"Duplicate document detected. Using existing job: {result['job_id']}")
                else:
                    st.success(f"Uploaded! Job ID: {result['job_id']}")

                st.session_state["current_job_id"] = result["job_id"]
                st.session_state["current_doc_id"] = result["document_id"]

                st.info("Navigate to 'Progress' to track processing status.")

            except Exception as e:
                st.error(f"Upload failed: {e}")

    elif submitted:
        st.warning("Please select a file to upload.")
