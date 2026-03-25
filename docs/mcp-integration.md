# DocExtract MCP Integration

DocExtract exposes document extraction and semantic search as [MCP (Model Context Protocol)](https://modelcontextprotocol.io) tools, allowing any MCP-compatible agent — Claude Desktop, custom agent frameworks — to process documents and query knowledge bases without custom integration code.

## Available MCP Tools

| Tool | Description | Required Inputs |
|------|-------------|-----------------|
| `extract_document` | Download a document from a URL and extract structured data using DocExtract AI. Supports PDF, images (PNG/JPEG/TIFF), email (.eml), and plain text. Returns the extracted record with document type, fields, and confidence score. | `file_url` (string) |
| `search_records` | Semantic search over all extracted records in DocExtract. Returns matching records with similarity scores. | `query` (string) |

### Tool Input Schemas

**`extract_document`**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file_url` | string | Yes | URL of the document to download and extract |
| `doc_type_hint` | string | No | Optional type hint: `invoice`, `purchase_order`, `receipt`, `bank_statement`, `identity_document`, `medical_record` |

**`search_records`**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Natural language search query |
| `limit` | integer | No | Max results to return (default: 5, max: 100) |

## Quick Setup

### 1. Install dependencies

```bash
pip install mcp httpx
```

### 2. Set environment variables

```bash
export DOCEXTRACT_API_URL="http://localhost:8000/api/v1"
export DOCEXTRACT_API_KEY="your-api-key"
```

Use the public demo key for read-only access: `demo-key-docextract-2026`

### 3. Configure Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "docextract": {
      "command": "python",
      "args": ["/path/to/docextract/mcp_server.py"],
      "env": {
        "DOCEXTRACT_API_URL": "http://localhost:8000/api/v1",
        "DOCEXTRACT_API_KEY": "your-api-key"
      }
    }
  }
}
```

See `docs/claude_desktop_config.example.json` for a copy-pasteable template.

### 4. Use in Claude

Once configured, Claude can call DocExtract tools directly:

> "Extract the invoice at https://example.com/invoice.pdf and tell me the total amount due."

> "Search my documents for contracts mentioning 'indemnification'."

> "Find all purchase orders from Acme Corp."

## How It Works

DocExtract's MCP server (`mcp_server.py`) wraps the REST API as typed tools. The server runs as a subprocess, communicates over stdio using the MCP protocol, and provides JSON Schema tool definitions that Claude uses for automatic tool selection.

**`extract_document` flow:**
1. Downloads the file from the provided URL
2. Uploads it to the DocExtract API (`POST /documents/upload`)
3. Polls the job status every 2 seconds until terminal state (up to 300s)
4. Fetches and returns the extracted record as JSON

**`search_records` flow:**
1. Sends the query to `GET /records/search` with the configured API key
2. Returns matching records with similarity scores as JSON

## Other MCP Hosts

The same `mcp_server.py` works with any MCP-compatible host. For Cursor or other editors, consult their MCP host documentation and use the same `command`/`args`/`env` pattern shown above.

## Related Projects

- **[mcp-server-toolkit](https://github.com/ChunkyTortoise/mcp-server-toolkit)** — 9 pre-built MCP servers and a framework for building new ones. Published to PyPI (`pip install mcp-server-toolkit==0.2.0`). Provides production boilerplate for building MCP servers with caching, rate limiting, and OpenTelemetry instrumentation — the same patterns used in this server.
- **[EnterpriseHub](https://github.com/ChunkyTortoise/EnterpriseHub)** — Multi-agent orchestration platform that uses MCP for tool dispatch across 22 specialized agents.
