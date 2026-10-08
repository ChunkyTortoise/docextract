# PostgreSQL schema installation and eval-log repair

This repair targets PostgreSQL 17 with pgvector. It fixes two fresh-install blockers and aligns `EvalLog.job_id` with the UUID job primary key while keeping its Python string interface.

Migration 001 already creates the two `updated_at` triggers. The corrected 007 removes each named trigger before recreating it, using one statement per asyncpg execution. Corrected 012 creates both eval-log IDs as PostgreSQL UUIDs. The new `013_eval_log_uuid_repair` follows 012 directly and converts legacy text IDs using explicit UUID casts. It also restores the exact `eval_log.job_id -> extraction_jobs.id` foreign key with `ON DELETE SET NULL` when missing or incorrectly configured. It rejects unexpected foreign keys involving `job_id` and preserves unrelated constraints.

## Historical migration exception

The 007 and 012 bodies change under the explicit approval for this repair. This is an exception to leaving applied revision bodies unchanged: a fresh database otherwise fails before reaching any forward repair. Existing databases stamped past these revisions do not rerun the corrected bodies. The new forward revision handles the named legacy compatibility shape.

This revision is independent of the unmerged record-deduplication work in PR #56/#57. Combining those branches later would introduce divergent successors of 012 and requires a deliberate revision-graph reconciliation. This repair does not delete duplicate records or import that schema change.

## Standalone acceptance

Use existing PostgreSQL 17, pgvector and Python dependencies. A host operator provisions nine separate empty local databases, each named `docextract_test_*`, and supplies a JSON manifest mapping these keys to `postgresql+asyncpg` connection URLs:

| Key | Acceptance |
|---|---|
| `metadata` | Full ORM metadata creates with the compatible UUID FK |
| `fresh` | Actual Alembic chain reaches head, indexes and triggers work, deleted jobs null their score references |
| `upgrade_011` | Existing 011 installation upgrades without losing its seeded job |
| `legacy` | Synthetic text IDs and nullable job references convert without losing scores |
| `uuid` | Correct UUID shape preserves scores |
| `missing_fk` | Correct UUID types with a missing job FK are repaired |
| `bad_uuid` | Invalid UUID text rejects conversion atomically |
| `orphan` | An orphaned job reference rejects FK creation atomically |
| `collision` | Text IDs that become the same UUID reject conversion atomically |

The test runner rejects nonlocal URLs, non-test database names, repeated targets and existing tables. It never creates or drops databases. The legacy fixtures are synthetic shapes without the impossible original VARCHAR-to-UUID FK; they do not claim the original 012 installed successfully on PostgreSQL.

From the candidate repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
DOCEXTRACT_SCHEMA_TEST_MANIFEST="$ISOLATED_SCHEMA_MANIFEST" \
/path/to/existing/python -m pytest --noconftest -p no:cacheprovider \
-o addopts= tests/integration/test_pg_schema_install.py -q
```

`--noconftest` excludes the shared SQLite metadata substitutions. Alembic and ORM creation also run in fresh Python subprocesses from neutral temporary working directories, with explicit source and connection bindings, so repository/home `.env` files cannot select the database. Keep credential-bearing URLs in the private manifest/environment; do not paste them into logs or commits. Without a manifest, these tests skip. Operators retain or remove disposable databases separately under their own authorization.

## Existing-database risks and limits

No production database migration or deployment is authorized by this acceptance route. Before any later real upgrade, inspect actual types, constraints, invalid UUID strings, UUID-equivalent ID collisions and orphaned references using read-only access. Back up the affected data and rehearse against a restored disposable copy. Cast or FK failures stop the migration; there is no automatic deletion, nulling or cleanup of invalid rows.

Column conversion and foreign-key replacement can lock tables. The forward revision leaves a canonical UUID/FK table unchanged, and alters only the exact job FK during conversion. A schema with unexpected `job_id` constraints requires explicit inspection rather than automatic removal.

The new revision's downgrade is intentionally a no-op. It does not recreate incompatible text types or reverse the conversion. Rolling back application code does not restore an old schema or replace a data backup. Historical migration 006 also replaces embedding data; these tests do not certify safe upgrades from every earlier deployed revision.

Acceptance covers the named isolated installation/compatibility scenarios. It does not establish production data safety, hosted deployment, external model quality or actual ARQ retries. Full-suite frontend collection currently has a separate installed Streamlit/Starlette incompatibility; this slice changes no dependencies.
