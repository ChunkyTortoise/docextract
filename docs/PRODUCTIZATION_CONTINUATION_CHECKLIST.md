# Productization Continuation Checklist

## Milestone A: Review Queue Hardening
- [ ] Add migration ensuring `validation_status` domain supports review lifecycle values.
- [ ] Add indexes for `(validation_status, needs_review, created_at)` and `(reviewed_by, reviewed_at)`.
- [ ] Add claim race-condition integration tests (parallel requests).

## Milestone B: Audit/SLA Reliability
- [ ] Ensure audit identity generation is consistent in SQLite and Postgres.
- [ ] Add rollback-on-audit-failure behavior tests.
- [ ] Add SLA breach fixture and deterministic breach-rate tests.

## Milestone C: ROI/Reporting
- [ ] Add typed response schemas for all `/roi` and `/reports` routes.
- [ ] Add `/api/v1/reports` listing endpoint.
- [ ] Add report generation failure-mode tests.

## Milestone D: Delivery Assets
- [ ] Add `scripts/smoke_productization.sh`.
- [ ] Add `docs/productization_api.md`.
- [ ] Add `docs/client_onboarding_runbook.md`.
- [ ] Add `docs/release_checklist.md`.
