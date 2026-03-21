"""Async HTTP client for DocExtract AI API."""
from __future__ import annotations

import httpx
import streamlit as st
from typing import Any


def get_client() -> httpx.Client:
    """Create configured httpx client with API key auth."""
    api_url = st.secrets.get("api_url", "http://localhost:8000")
    api_key = st.session_state.get("api_key") or st.secrets.get("api_key", "")
    return httpx.Client(
        base_url=f"{api_url}/api/v1",
        headers={"X-API-Key": api_key},
        timeout=30.0,
    )


def upload_document(
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    priority: str = "normal",
    document_type_override: str | None = None,
) -> dict[str, Any]:
    """Upload a document for processing."""
    with get_client() as client:
        response = client.post(
            "/documents/upload",
            files={"file": (filename, file_bytes, mime_type)},
            data={
                "priority": priority,
                **({"document_type_override": document_type_override} if document_type_override else {}),
            },
        )
        response.raise_for_status()
        return response.json()


def batch_upload(
    files: list[tuple[str, bytes, str]],  # [(filename, bytes, mime_type), ...]
    priority: str = "normal",
) -> dict[str, Any]:
    """Upload multiple documents for batch processing."""
    with get_client() as client:
        file_tuples = [("files", (name, data, mime)) for name, data, mime in files]
        response = client.post(
            "/documents/batch",
            files=file_tuples,
            data={"priority": priority},
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()


def get_job(job_id: str) -> dict[str, Any]:
    """Get job status."""
    with get_client() as client:
        response = client.get(f"/jobs/{job_id}")
        response.raise_for_status()
        return response.json()


def get_job_record(job_id: str) -> dict[str, Any]:
    """Get the extracted record for a specific job."""
    with get_client() as client:
        response = client.get(f"/jobs/{job_id}/record")
        response.raise_for_status()
        return response.json()


def get_records(
    page: int = 1,
    page_size: int = 20,
    document_type: str | None = None,
    needs_review: bool | None = None,
    min_confidence: float | None = None,
) -> dict[str, Any]:
    """Get paginated records with optional filters."""
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if document_type:
        params["document_type"] = document_type
    if needs_review is not None:
        params["needs_review"] = needs_review
    if min_confidence is not None:
        params["min_confidence"] = min_confidence

    with get_client() as client:
        response = client.get("/records", params=params)
        response.raise_for_status()
        return response.json()


def get_record(record_id: str) -> dict[str, Any]:
    """Get single record with full extracted data."""
    with get_client() as client:
        response = client.get(f"/records/{record_id}")
        response.raise_for_status()
        return response.json()


def review_record(
    record_id: str,
    decision: str,
    corrections: dict | None = None,
    reviewer_notes: str | None = None,
) -> dict[str, Any]:
    """Submit review decision for a record."""
    with get_client() as client:
        response = client.patch(
            f"/records/{record_id}/review",
            json={
                "decision": decision,
                "corrections": corrections,
                "reviewer_notes": reviewer_notes,
            },
        )
        response.raise_for_status()
        return response.json()


def search_records(query: str, limit: int = 10) -> dict[str, Any]:
    """Search records using semantic search."""
    with get_client() as client:
        response = client.get("/records/search", params={"q": query, "limit": limit})
        response.raise_for_status()
        return response.json()


def export_records(format: str = "csv", document_type: str | None = None) -> bytes:
    """Export all records as CSV or JSON bytes."""
    params: dict[str, Any] = {"format": format}
    if document_type:
        params["document_type"] = document_type

    with get_client() as client:
        response = client.get("/records/export", params=params)
        response.raise_for_status()
        return response.content


def list_jobs(
    page: int = 1,
    page_size: int = 100,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List jobs with optional status filter."""
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if status:
        params["status"] = status
    with get_client() as client:
        response = client.get("/jobs", params=params)
        response.raise_for_status()
        return response.json()


def get_stats() -> dict[str, Any]:
    """Get aggregate statistics."""
    with get_client() as client:
        response = client.get("/stats")
        response.raise_for_status()
        return response.json()


def cancel_job(job_id: str) -> dict[str, Any]:
    """Cancel a queued or processing job."""
    with get_client() as client:
        response = client.patch(f"/jobs/{job_id}", json={"action": "cancel"})
        response.raise_for_status()
        return response.json()


def delete_document(document_id: str) -> None:
    """Delete a document and its associated data."""
    with get_client() as client:
        response = client.delete(f"/documents/{document_id}")
        response.raise_for_status()


def get_roi_summary(date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
    """Get ROI summary metrics."""
    params: dict[str, Any] = {}
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    with get_client() as client:
        response = client.get("/roi/summary", params=params)
        response.raise_for_status()
        return response.json()


def get_roi_trends(
    interval: str = "week",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Get ROI trend data over time."""
    params: dict[str, Any] = {"interval": interval}
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    with get_client() as client:
        response = client.get("/roi/trends", params=params)
        response.raise_for_status()
        return response.json()


def generate_report(
    date_from: str | None = None,
    date_to: str | None = None,
    format: str = "both",
) -> dict[str, Any]:
    """Generate an ROI report."""
    payload: dict[str, Any] = {"format": format}
    if date_from:
        payload["date_from"] = date_from
    if date_to:
        payload["date_to"] = date_to
    with get_client() as client:
        response = client.post("/roi/reports", json=payload)
        response.raise_for_status()
        return response.json()


def list_reports(limit: int = 20) -> dict[str, Any]:
    """List generated ROI reports."""
    with get_client() as client:
        response = client.get("/roi/reports", params={"limit": limit})
        response.raise_for_status()
        return response.json()


def get_report(report_id: str) -> dict[str, Any]:
    """Get a specific ROI report."""
    with get_client() as client:
        response = client.get(f"/roi/reports/{report_id}")
        response.raise_for_status()
        return response.json()


def get_review_items(
    status: str | None = None,
    assignee: str | None = None,
    doc_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Get paginated review queue items."""
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if status:
        params["status"] = status
    if assignee:
        params["assignee"] = assignee
    if doc_type:
        params["doc_type"] = doc_type
    with get_client() as client:
        response = client.get("/review/queue", params=params)
        response.raise_for_status()
        return response.json()


def claim_review_item(item_id: str) -> dict[str, Any]:
    """Claim a review queue item."""
    with get_client() as client:
        response = client.post(f"/review/queue/{item_id}/claim")
        response.raise_for_status()
        return response.json()


def approve_review_item(item_id: str) -> dict[str, Any]:
    """Approve a review queue item."""
    with get_client() as client:
        response = client.post(f"/review/queue/{item_id}/approve")
        response.raise_for_status()
        return response.json()


def correct_review_item(
    item_id: str,
    corrections: dict,
    reviewer_notes: str | None = None,
) -> dict[str, Any]:
    """Submit corrections for a review queue item."""
    payload: dict[str, Any] = {"corrections": corrections}
    if reviewer_notes:
        payload["reviewer_notes"] = reviewer_notes
    with get_client() as client:
        response = client.post(f"/review/queue/{item_id}/correct", json=payload)
        response.raise_for_status()
        return response.json()


def get_review_metrics(stale_after_hours: int = 24) -> dict[str, Any]:
    """Get review queue metrics."""
    with get_client() as client:
        response = client.get("/review/metrics", params={"stale_after_hours": stale_after_hours})
        response.raise_for_status()
        return response.json()
