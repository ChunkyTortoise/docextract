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
import ipaddress
import json
import os
import socket
import urllib.parse
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


_BLOCKED_HOSTS = {"localhost", "metadata", "metadata.google.internal", "instance-data"}
_BLOCKED_SUFFIXES = (".localhost", ".internal", ".local")


# IPv6 prefixes whose low 32 bits carry an IPv4 address a gateway or stack may route to.
_IPV4_EMBEDDING_V6_NETS = (
    ipaddress.IPv6Network("::/96"),  # IPv4-compatible (deprecated, RFC 4291)
    ipaddress.IPv6Network("::ffff:0:0:0/96"),  # IPv4-translated (RFC 2765)
    ipaddress.IPv6Network("64:ff9b::/96"),  # NAT64 well-known prefix (RFC 6052)
    ipaddress.IPv6Network("64:ff9b:1::/48"),  # NAT64 local-use prefix (RFC 8215)
)


def _embedded_ipv4(addr: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    """Return IPv4 addresses embedded in an IPv6 address (mapped, 6to4, Teredo, NAT64, compat)."""
    found: list[ipaddress.IPv4Address] = []
    if addr.ipv4_mapped:
        found.append(addr.ipv4_mapped)
    if addr.sixtofour:
        found.append(addr.sixtofour)
    if addr.teredo:
        found.extend(addr.teredo)
    if any(addr in net for net in _IPV4_EMBEDDING_V6_NETS):
        found.append(ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF))
    return found


def _is_public_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        else:
            # is_global alone misses NAT64 / IPv4-compatible forms (and 6to4 on older
            # Pythons), so every embedded IPv4 must be public as well.
            embedded = _embedded_ipv4(addr)
            if embedded and not all(_is_public_ip(v4) for v4 in embedded):
                return False
            # Deprecated site-local space (fec0::/10, RFC 3879) still counts as global
            # in CPython's ipaddress, but it is internal wherever a network keeps it.
            if addr.is_site_local:
                return False
    # is_global also rejects shared address space (100.64/10), which is_private misses.
    return addr.is_global and not addr.is_multicast


def _validate_fetch_url(url: str) -> None:
    """Reject non-https URLs and hosts that are, or resolve to, non-public addresses.

    Known limitation: this checks DNS at validation time only. httpx resolves the
    name again when it connects, so a DNS-rebinding host can still pass. Closing that
    needs connection-time IP pinning (custom transport) or an egress firewall.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Only https URLs are allowed; got scheme '{parsed.scheme}'")
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if not hostname:
        raise ValueError("URL has no host")
    if hostname in _BLOCKED_HOSTS or hostname.endswith(_BLOCKED_SUFFIXES):
        raise ValueError(f"Requests to internal hostnames are not allowed: {hostname}")

    # Legacy IPv4 forms (127.1, 0x7f.1, 2130706433, 0177.0.0.1) via inet_aton.
    candidates: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    try:
        candidates.append(ipaddress.ip_address(hostname))
    except ValueError:
        try:
            candidates.append(ipaddress.IPv4Address(socket.inet_aton(hostname)))
        except OSError:
            # Not an IP literal: resolve and check every returned address.
            try:
                infos = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
            except socket.gaierror as exc:
                raise ValueError(f"Cannot resolve host: {hostname}") from exc
            candidates.extend(ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos)

    if not candidates or not all(_is_public_ip(a) for a in candidates):
        raise ValueError(f"Requests to private/loopback addresses are not allowed: {hostname}")


async def _extract_document(
    file_url: str,
    doc_type_hint: str | None = None,
) -> list[TextContent]:
    """Download file from URL, upload to DocExtract, poll until complete."""
    _validate_fetch_url(file_url)
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
