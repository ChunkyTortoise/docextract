# ADR-0012: Pluggable Storage Backend (Local/R2)

**Status**: Accepted
**Date**: 2026-03

## Context

Document files must be stored durably between upload and processing. In development, writing to local disk is fast and requires no external dependencies. In production, local disk is lost on redeploy (Render ephemeral filesystem) and cannot be shared between API and Worker services. A vendor-specific implementation in the upload path would make local testing require cloud credentials.

## Decision

Implement a `StorageBackend` abstract base class (`app/storage/base.py`) with two concrete implementations: `LocalStorage` (`app/storage/local.py`) and `CloudflareR2Storage` (`app/storage/r2.py`). The active backend is selected at startup via the `STORAGE_BACKEND` environment variable (`local` or `r2`).

## Consequences

**Why:** The abstraction lets the API and Worker services share the same storage interface regardless of backend. Local development uses `local` with no credentials; production uses `r2` with R2 bucket credentials. Switching backends requires changing one environment variable, not the application code. The `base.py` interface (`upload`, `download`, `delete`, `get_url`) is small enough that adding a third backend (S3, GCS) is a one-file addition.

Cloudflare R2 was selected over AWS S3 for the production backend because R2 has zero egress fees — document downloads from the Worker back to the API for processing are free. At DocExtract's target scale, egress costs from S3 would add up quickly.

**Tradeoff:** The abstraction adds a layer of indirection that slightly obscures which backend is active during debugging. Accepted because the clarity benefit in tests (always use `LocalStorage`) and the operational flexibility (swap backends without code changes) outweigh the minor indirection cost.
