# ADR-0011: API Key Authentication over OAuth/JWT

**Status**: Accepted
**Date**: 2026-03

## Context

DocExtract exposes HTTP endpoints for document upload, job management, and record retrieval. These endpoints are consumed by server-to-server integrations (CI pipelines, ETL scripts, enterprise data platforms) rather than by human users via a browser. Authentication must be simple to issue, easy to rotate, and auditable per-key.

## Decision

Implement API key authentication using PBKDF2-HMAC-SHA256 hashed keys stored in PostgreSQL, with per-key Redis rate limiting. Reject OAuth 2.0 and JWT bearer tokens.

## Consequences

**Why:** OAuth 2.0 and JWT are designed for delegated authorization in user-facing flows — they require an authorization server, client registration, token refresh flows, and audience validation. DocExtract's consumers are server processes that never involve a human authorization step. API keys are a better fit: one static credential per integration, revocable without re-authorizing a human user, and auditable at the key level in the `api_keys` table.

PBKDF2-HMAC-SHA256 hashing means the raw key is never stored — a compromised database does not expose usable credentials. Per-key Redis rate limiting (sliding window) prevents any single key from causing API abuse.

**Tradeoff:** API keys do not expire automatically and must be manually rotated. They also cannot encode scoped permissions as richly as OAuth scopes or JWT claims. Accepted because DocExtract's permission model is binary (authenticated vs. unauthenticated) — there are no user-level resource ownership boundaries that would require OAuth's delegated authorization model.
