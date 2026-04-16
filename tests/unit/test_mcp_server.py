"""Unit tests for mcp_server.py — all httpx calls are mocked."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("DOCEXTRACT_API_URL", "http://test-api/api/v1")
    monkeypatch.setenv("DOCEXTRACT_API_KEY", "test-key-123")


class TestListTools:
    @pytest.mark.asyncio
    async def test_list_tools_returns_two_tools(self, mock_env):
        import importlib

        import mcp_server
        importlib.reload(mcp_server)

        tools = await mcp_server.list_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"extract_document", "search_records"}

    @pytest.mark.asyncio
    async def test_extract_document_tool_has_required_file_url(self, mock_env):
        import importlib

        import mcp_server
        importlib.reload(mcp_server)

        tools = await mcp_server.list_tools()
        extract_tool = next(t for t in tools if t.name == "extract_document")
        assert "file_url" in extract_tool.inputSchema["properties"]
        assert "file_url" in extract_tool.inputSchema["required"]
        assert "doc_type_hint" in extract_tool.inputSchema["properties"]

    @pytest.mark.asyncio
    async def test_search_records_tool_has_required_query(self, mock_env):
        import importlib

        import mcp_server
        importlib.reload(mcp_server)

        tools = await mcp_server.list_tools()
        search_tool = next(t for t in tools if t.name == "search_records")
        assert "query" in search_tool.inputSchema["properties"]
        assert "query" in search_tool.inputSchema["required"]

    @pytest.mark.asyncio
    async def test_server_name_is_docextract(self, mock_env):
        import importlib

        import mcp_server
        importlib.reload(mcp_server)

        assert mcp_server.server.name == "docextract"


class TestSearchRecords:
    @pytest.mark.asyncio
    async def test_search_returns_results(self, mock_env):
        import importlib

        import mcp_server
        importlib.reload(mcp_server)

        mock_results = [
            {"record": {"id": "abc", "document_type": "invoice"}, "similarity": 0.95}
        ]

        mock_response = MagicMock()
        mock_response.json.return_value = mock_results
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await mcp_server._search_records("invoice from Acme", limit=5)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data[0]["similarity"] == 0.95

    @pytest.mark.asyncio
    async def test_search_caps_limit_at_100(self, mock_env):
        import importlib

        import mcp_server
        importlib.reload(mcp_server)

        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await mcp_server._search_records("test", limit=999)

        call_kwargs = mock_client.get.call_args
        assert call_kwargs.kwargs["params"]["limit"] == 100

    @pytest.mark.asyncio
    async def test_search_returns_text_content(self, mock_env):
        import importlib

        import mcp_server
        importlib.reload(mcp_server)

        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await mcp_server._search_records("test")

        assert result[0].type == "text"


class TestExtractDocument:
    @pytest.mark.asyncio
    async def test_extract_polls_until_completed(self, mock_env):
        import importlib

        import mcp_server
        importlib.reload(mcp_server)

        file_bytes = b"%PDF-1.4 fake content"
        upload_result = {"job_id": "job-123", "document_id": "doc-456"}
        job_completed = {"status": "completed", "id": "job-123"}
        record_result = {
            "id": "rec-789",
            "document_type": "invoice",
            "extracted_data": {"invoice_number": "INV-001"},
            "confidence_score": 0.92,
        }

        dl_response = MagicMock()
        dl_response.content = file_bytes
        dl_response.raise_for_status = MagicMock()

        upload_response = MagicMock()
        upload_response.json.return_value = upload_result
        upload_response.raise_for_status = MagicMock()

        job_response = MagicMock()
        job_response.json.return_value = job_completed
        job_response.raise_for_status = MagicMock()

        record_response = MagicMock()
        record_response.json.return_value = record_result
        record_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        # get calls: download, job status, record
        mock_client.get = AsyncMock(side_effect=[dl_response, job_response, record_response])
        mock_client.post = AsyncMock(return_value=upload_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await mcp_server._extract_document("http://example.com/inv.pdf")

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["document_type"] == "invoice"
        assert data["confidence_score"] == 0.92

    @pytest.mark.asyncio
    async def test_extract_raises_on_failed_job(self, mock_env):
        import importlib

        import mcp_server
        importlib.reload(mcp_server)

        file_bytes = b"fake pdf"
        upload_result = {"job_id": "job-fail", "document_id": "doc-fail"}
        job_failed = {"status": "failed", "error_message": "Claude API error"}

        dl_response = MagicMock()
        dl_response.content = file_bytes
        dl_response.raise_for_status = MagicMock()

        upload_response = MagicMock()
        upload_response.json.return_value = upload_result
        upload_response.raise_for_status = MagicMock()

        job_response = MagicMock()
        job_response.json.return_value = job_failed
        job_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[dl_response, job_response])
        mock_client.post = AsyncMock(return_value=upload_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError, match="Claude API error"):
                await mcp_server._extract_document("http://example.com/doc.pdf")

    @pytest.mark.asyncio
    async def test_extract_raises_on_cancelled_job(self, mock_env):
        import importlib

        import mcp_server
        importlib.reload(mcp_server)

        dl_response = MagicMock()
        dl_response.content = b"fake"
        dl_response.raise_for_status = MagicMock()

        upload_response = MagicMock()
        upload_response.json.return_value = {"job_id": "j1", "document_id": "d1"}
        upload_response.raise_for_status = MagicMock()

        job_response = MagicMock()
        job_response.json.return_value = {"status": "cancelled"}
        job_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[dl_response, job_response])
        mock_client.post = AsyncMock(return_value=upload_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError, match="cancelled"):
                await mcp_server._extract_document("http://example.com/doc.pdf")

    @pytest.mark.asyncio
    async def test_call_tool_unknown_raises(self, mock_env):
        import importlib

        import mcp_server
        importlib.reload(mcp_server)

        with pytest.raises(ValueError, match="Unknown tool"):
            await mcp_server.call_tool("nonexistent_tool", {})

    @pytest.mark.asyncio
    async def test_extract_passes_doc_type_hint(self, mock_env):
        import importlib

        import mcp_server
        importlib.reload(mcp_server)

        dl_response = MagicMock()
        dl_response.content = b"invoice content"
        dl_response.raise_for_status = MagicMock()

        upload_response = MagicMock()
        upload_response.json.return_value = {"job_id": "j1", "document_id": "d1"}
        upload_response.raise_for_status = MagicMock()

        job_response = MagicMock()
        job_response.json.return_value = {"status": "completed"}
        job_response.raise_for_status = MagicMock()

        record_response = MagicMock()
        record_response.json.return_value = {"id": "r1", "document_type": "invoice"}
        record_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[dl_response, job_response, record_response])
        mock_client.post = AsyncMock(return_value=upload_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await mcp_server._extract_document(
                "http://example.com/inv.pdf",
                doc_type_hint="invoice",
            )

        post_kwargs = mock_client.post.call_args
        assert post_kwargs.kwargs["data"]["document_type_override"] == "invoice"
