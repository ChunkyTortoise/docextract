# Productization Continuation Checklist

## Milestone A: Review Queue Hardening
- [x] Add migration ensuring `validation_status` domain supports review lifecycle values.
- [x] Add indexes for `(validation_status, needs_review, created_at)` and `(reviewed_by, reviewed_at)`.
- [x] Add claim race-condition integration tests (parallel requests).

## Milestone B: Audit/SLA Reliability
- [x] Ensure audit identity generation is consistent in SQLite and Postgres.
- [x] Add rollback-on-audit-failure behavior tests.
- [x] Add SLA breach fixture and deterministic breach-rate tests.

## Milestone C: ROI/Reporting
- [x] Add typed response schemas for all `/roi` and `/reports` routes.
- [x] Add `/api/v1/reports` listing endpoint.
- [x] Add report generation failure-mode tests.

## Milestone D: Delivery Assets
- [x] Add `scripts/smoke_productization.sh`.
- [x] Add `docs/productization_api.md`.
- [x] Add `docs/client_onboarding_runbook.md`.
- [x] Add `docs/release_checklist.md`.

## Milestone E: Demo UI
- [x] Add `GET /demo` endpoint serving static HTML.
- [x] Add `app/static/demo.html` self-contained portfolio demo page.
- [x] Add demo mode integration tests (7 tests).
- [x] Add DEMO_MODE env var to render.yaml.
- [x] Add demo mode banners to Streamlit upload and review pages.
