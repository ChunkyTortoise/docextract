# ADR-0005: SSE over WebSocket for Job Progress Streaming

**Status**: Accepted
**Date**: 2026-01

## Context

Document processing jobs run for 5-30 seconds. The UI must display live progress (queued → processing → extracting → completed). Communication is inherently one-directional: server emits status, client listens.

## Decision

Use Server-Sent Events (SSE) over WebSocket for streaming job progress updates.

## Consequences

**Why:** Job progress is unidirectional — SSE is designed exactly for this pattern. It uses HTTP/1.1 with no upgrade handshake, works through standard reverse proxies (Nginx, Render's load balancer) without special configuration, and reconnects automatically via the browser's `EventSource` API. WebSockets require a protocol upgrade, persistent bidirectional state, and proxy support that is inconsistent across hosting platforms.

**Tradeoff:** SSE cannot send binary data and does not support client-to-server messages. If DocExtract ever needed interactive extraction (streaming partial JSON tokens to a browser editor), WebSocket would be the right choice. Accepted because the current use case — one-way progress updates until completion — maps precisely to SSE's strengths.
