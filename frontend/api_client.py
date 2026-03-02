"""Async HTTP client for DocExtract AI API."""
from __future__ import annotations

import httpx
import streamlit as st
from typing import Any


def get_client() -> httpx.Client:
    """Create configured httpx client with API key auth."""
    api_url = st.secrets.get("api_url", "http://localhost:8000")
    api_key = st.secrets.get("api_key", "")
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


def get_job(job_id: str) -> dict[str, Any]:
    """Get job status."""
    with get_client() as client:
        response = client.get(f"/jobs/{job_id}")
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


def export_records(format: str = "csv", document_type: str | None = None) -> bytes:
    """Export all records as CSV or JSON bytes."""
    params: dict[str, Any] = {"format": format}
    if document_type:
        params["document_type"] = document_type

    with get_client() as client:
        response = client.get("/records/export", params=params)
        response.raise_for_status()
        return response.content


def get_stats() -> dict[str, Any]:
    """Get aggregate statistics."""
    with get_client() as client:
        response = client.get("/stats")
        response.raise_for_status()
        return response.json()
