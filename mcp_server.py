"""MCP tool server for DocExtract AI.

Exposes two tools:
  - extract_document: download URL, upload to DocExtract, poll until complete, return record
  - search_records: semantic search over extracted records

Config via env:
  DOCEXTRACT_API_URL  (default: http://localhost:8000/api/v1)
  DOCEXTRACT_API_KEY  (required)
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

API_URL = os.environ.get("DOCEXTRACT_API_URL", "http://localhost:8000/api/v1").rstrip("/")
API_KEY = os.environ.get("DOCEXTRACT_API_KEY", "")
POLL_INTERVAL = 2  # seconds between job status polls
POLL_TIMEOUT = 300  # max seconds to wait for completion

server = Server("docextract")


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="extract_document",
            description=(
                "Download a document from a URL and extract structured data using DocExtract AI. "
                "Supports PDF, images (PNG/JPEG/TIFF), email (.eml), and plain text. "
                "Returns the extracted record with document type, fields, and confidence score."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_url": {
                        "type": "string",
                        "description": "URL of the document to download and extract",
                    },
                    "doc_type_hint": {
                        "type": "string",
                        "description": (
                            "Optional document type hint: invoice, purchase_order, receipt, "
                            "bank_statement, identity_document, medical_record"
                        ),
                    },
                },
                "required": ["file_url"],
            },
        ),
        Tool(
            name="search_records",
            description=(
                "Semantic search over all extracted records in DocExtract. "
                "Returns matching records with similarity scores."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 5, max: 100)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "extract_document":
        return await _extract_document(
            file_url=arguments["file_url"],
            doc_type_hint=arguments.get("doc_type_hint"),
        )
    if name == "search_records":
        return await _search_records(
            query=arguments["query"],
            limit=arguments.get("limit", 5),
        )
    raise ValueError(f"Unknown tool: {name}")


async def _extract_document(
    file_url: str,
    doc_type_hint: str | None = None,
) -> list[TextContent]:
    """Download file from URL, upload to DocExtract, poll until complete."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Download file from URL
        dl_response = await client.get(file_url)
        dl_response.raise_for_status()
        file_bytes = dl_response.content

        # Detect filename from URL
        filename = file_url.split("/")[-1].split("?")[0] or "document"

        # Upload to DocExtract
        files = {"file": (filename, file_bytes)}
        data: dict[str, str] = {}
        if doc_type_hint:
            data["document_type_override"] = doc_type_hint

        upload_response = await client.post(
            f"{API_URL}/documents/upload",
            headers=_headers(),
            files=files,
            data=data,
        )
        upload_response.raise_for_status()
        upload_result = upload_response.json()
        job_id = upload_result["job_id"]

        # Poll job until terminal status
        record = await _poll_job(client, job_id)

    return [TextContent(type="text", text=json.dumps(record, indent=2, default=str))]


async def _poll_job(client: httpx.AsyncClient, job_id: str) -> dict[str, Any]:
    """Poll GET /jobs/{job_id} until terminal status, return extracted record."""
    terminal = {"completed", "needs_review", "failed", "cancelled"}
    elapsed = 0

    while elapsed < POLL_TIMEOUT:
        response = await client.get(
            f"{API_URL}/jobs/{job_id}",
            headers=_headers(),
        )
        response.raise_for_status()
        job = response.json()
        status = job.get("status", "").lower()

        if status in terminal:
            if status == "failed":
                raise RuntimeError(
                    f"DocExtract job failed: {job.get('error_message', 'unknown error')}"
                )
            if status == "cancelled":
                raise RuntimeError("DocExtract job was cancelled")

            # Fetch the extracted record
            record_response = await client.get(
                f"{API_URL}/jobs/{job_id}/record",
                headers=_headers(),
            )
            record_response.raise_for_status()
            return record_response.json()

        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    raise TimeoutError(f"Job {job_id} did not complete within {POLL_TIMEOUT}s")


async def _search_records(query: str, limit: int = 5) -> list[TextContent]:
    """Search extracted records by semantic query."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{API_URL}/records/search",
            headers=_headers(),
            params={"q": query, "limit": min(limit, 100)},
        )
        response.raise_for_status()
        results = response.json()

    return [TextContent(type="text", text=json.dumps(results, indent=2, default=str))]


async def main() -> None:
    async with stdio_server() as streams:
        await server.run(*streams, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
