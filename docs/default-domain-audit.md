# Server-default domain audit (the "015 class")

Date: 2026-09-26. Scope: rec **R-default-audit** — audit remaining columns for
server defaults that fall outside their check-constraint domains. Report-first
and doc+test only: no migrations or production code changed here. Any migration
(e.g. the 010 cast nit below) needs a second explicit ask.

The 015 class of bug: a column's DB-level `server_default` violates the domain
its check constraint enforces, so the first raw INSERT that omits the column
fails. The known instance was `extracted_records.validation_status`: 001 set
`'pending'` while 005's `ck_extracted_records_validation_status_domain` allows
`('pending_review','claimed','approved','corrected','passed','failed')`. 015
moved the server default to `'pending_review'`.

## Method

- Static review of all 15 Alembic revisions (`alembic/versions/001..015`) for
  `server_default` expressions and every `create_check_constraint`.
- Cross-check of each literal default against the column's enforced domain
  (DB check constraint > native enum type > app-level domain), plus
  model-vs-migration default parity for the same columns.
- Machine guard added (see below) so the class stays caught:
  `tests/unit/test_migrations.py::TestServerDefaultDomains` scans every
  migration and asserts the *effective* default of each column (chronological
  `create`/`add_column`/`alter_column` sequence) is inside its check-constraint
  domain, and that the model-side default agrees.

## Constraint inventory

- DB-level domain constraints repo-wide: exactly one —
  `ck_extracted_records_validation_status_domain` (`extracted_records`,
  005 + model `app/models/record.py`).
- Native PG enum types: none.
- All other value domains are app-level only (`JobStatus`, request `Literal`s,
  `Field(pattern=...)`, comment-documented sets) and are not DB-enforced.

## Literal server defaults — full inventory and verdicts

| Table.column | Revision | server_default | Domain enforcement | Verdict |
| --- | --- | --- | --- | --- |
| `extracted_records.validation_status` | 001 → 015 | `'pending_review'` (was `'pending'`) | DB check (005) | **Fixed by 015**; effective default in-domain, model default `"pending_review"` matches |
| `extraction_jobs.status` | 001 | `'queued'` | app `JobStatus` StrEnum | In-domain (`JobStatus.QUEUED = "queued"`) |
| `extraction_jobs.priority` | 001 | `'standard'` | app `Literal["normal","high","express","standard"]` | In-domain (note: the Literal accepts both `"normal"` and `"standard"`; only `"standard"` is ever defaulted) |
| `api_keys.role` | 004 | `'admin'` | app `Field(pattern="^(admin\|operator\|viewer)$")` | In-domain, but see finding 2 |
| `executive_reports.format` | 005 | `'both'` | app (request payload format) | In-domain; all writes pass `format` explicitly |
| `executive_reports.status` | 005 | `'generated'` | app (writes use `"generated"`/`"failed"`) | In-domain; all writes pass `status` explicitly |
| `llm_traces.status` | 008 | `'success'` | app (domain `success`/`error`/`timeout`, `llm_tracer.py`) | In-domain |
| `api_keys.is_active` | 001 | `true` | boolean type | N/A (type-valid) |
| `extracted_records.needs_review` | 001 | `false` | boolean type | N/A |
| `extraction_jobs.retryable` | 001 | `true` | boolean type | N/A |
| `api_keys.rate_limit_per_minute` | 001 | `60` | integer type | N/A (no range constraint exists) |
| `extraction_jobs.progress_pct` | 001 | `0` | integer type | N/A (no range constraint exists) |
| `extraction_jobs.extraction_pass_count`, `input_tokens_used`, `output_tokens_used` | 001 | `0` | integer type | N/A |
| `extraction_jobs.attempt_number` | 001 | `1` | integer type | N/A (recovery logic maintains `>= 1`) |
| `llm_traces.retries` | 008 | `0` | integer type | N/A |
| `executive_reports.files_json` | 005 | `'[]'::jsonb` | JSONB type (explicit cast) | Type-valid |
| `executive_reports.summary_json` | 005 | `'{}'::jsonb` | JSONB type (explicit cast) | Type-valid |
| `eval_history.metadata` | 010 | `'{}'` | JSONB type | Type-valid; see finding 3 |

Expression defaults (`gen_random_uuid()`, `NOW()`/`now()`, `sa.func.now()`) are
type-matched by construction and are outside this audit's failure class; they
were checked only for column-type fit (all uuid/timestamp, all fit, including
012's post-014 uuid-shaped `eval_log` keys).

## Findings

1. **No remaining default-outside-domain violations.** The only DB-enforced
   domain in the repo is `ck_extracted_records_validation_status_domain`, and
   015 already made its effective default domain-valid. Every other literal
   default is in-domain at the app level (table above).
2. **`api_keys.role` default is in-domain but over-privileged.** The DB
   server_default is `'admin'` (004) and the SQLAlchemy default is `"admin"`,
   while the API create schema defaults to `"viewer"`. A raw INSERT that omits
   `role` therefore grants admin. Not a domain violation, but the least-value
   default would be `'viewer'`. Report-first: a fix is a migration (drop or
   change the server default) and needs a second explicit ask.
3. **`eval_history.metadata` (010) omits the `::jsonb` cast** that 005 uses for
   its JSONB defaults. PostgreSQL infers the literal type from the column, so
   behavior is correct today (pg suite passes); this is a consistency nit, not
   a bug. Migration-only fix; needs a second explicit ask.
4. **App-only domains are unguarded at the DB level.** `extraction_jobs.status`,
   `extraction_jobs.priority`, `api_keys.role`, `executive_reports.format`,
   `executive_reports.status`, `llm_traces.status` rely on app validation. If
   any check constraint is added for these later, re-run this audit — the
   guard test in `tests/unit/test_migrations.py` already covers any new
   constraint-free default automatically (it scans all migrations, not a fixed
   list).

## Guard added

`tests/unit/test_migrations.py::TestServerDefaultDomains`:

- Walks every file in `alembic/versions/` with `ast`, tracks the effective
  `server_default` per `(table, column)` across `create_table`/`add_column`/
  `alter_column` in revision order, collects every `IN (...)` check-constraint
  domain, and asserts each effective literal default is inside its domain
  (the 015 class). Asserts the known constraint is found so the scan cannot
  pass vacuously.
- Asserts `ExtractedRecord.validation_status`'s model default is in-domain and
  equals the effective server default (model/migration parity — the 015 bug
  shape).

Not done here (needs a second explicit ask): migration for finding 2 or 3.
