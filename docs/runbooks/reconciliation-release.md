# Reconciliation release gate

The reconciliation branch is a review candidate. Publishing its PR does not
approve merging to main, deploying, or migrating an existing application database.

## Deployment boundary

The checked-in Render API `preDeployCommand` runs `alembic upgrade head` and demo
seeding. The release checklist describes main auto-deployment; confirm the actual
service branch, automatic deploy setting, and preview configuration in Render
before merging. GitHub CI publishes container images only on pushes to main.
No live Render configuration or existing application database was inspected as
part of the reconciliation review.

Before an approved deployment, configure `DEMO_API_KEY` explicitly on the API and
any frontend that uses its read-only demo bypass. The default is empty. With an
empty default, anonymous API access is denied; `/demo` still renders labeled
synthetic fixtures without calling the API. Cached Streamlit demo data is separate
from that API credential. Verify both the anonymous page and intended API access
on the deployed service.

## Migration 013: inspect and preserve dependent data

Migration 013 keeps the earliest record for each job, ordered by `created_at` and
then `id`, and deletes the others before creating a unique index. It does not
choose the newest reviewed or corrected record. Those deletes also remove related
`content_embeddings` and `validation_errors` through foreign-key cascades.
`corrections.record_id`, `feedback.record_id`, and record audit-log entity IDs have
no foreign keys; their rows survive with references to deleted records. The
optional file-backed graph index and external record links are not rewritten.

Do not deploy until the operator has:

1. Paused ingestion and workers, confirmed the target DB and current revision,
   and taken a full backup with a tested restore procedure.
2. Exported the duplicate-to-survivor mapping and all affected records and
   dependent rows into protected backup storage. Keep document and job IDs so
   the record history can be reconstructed.
3. Reviewed corrections, feedback, audit history, validation errors, and graph
   entries for the records that would be removed. If any need reconciliation,
   agree on that plan before running the migration. Do not silently assign a
   correction to a different extracted result.
4. Rehearsed the upgrade and validation on a restored disposable copy, then
   explicitly approved applying the migration to the existing database.

This read-only PostgreSQL query identifies affected rows and direct DB dependencies
at revision 012. Run it only against the intended target with read-only access;
its output contains record identifiers and should remain in protected storage.

```sql
WITH ranked AS (
    SELECT id, job_id, created_at,
           first_value(id) OVER (
               PARTITION BY job_id ORDER BY created_at, id
           ) AS keep_id,
           row_number() OVER (
               PARTITION BY job_id ORDER BY created_at, id
           ) AS position
    FROM extracted_records
)
SELECT r.job_id, r.id AS removed_id, r.keep_id, r.created_at,
       (SELECT count(*) FROM content_embeddings e WHERE e.record_id = r.id) AS embeddings,
       (SELECT count(*) FROM validation_errors v WHERE v.record_id = r.id) AS validation_errors,
       (SELECT count(*) FROM corrections c WHERE c.record_id = r.id::text) AS corrections,
       (SELECT count(*) FROM feedback f WHERE f.record_id = r.id::text) AS feedback,
       (SELECT count(*) FROM audit_logs a
        WHERE a.entity_type = 'record' AND a.entity_id = r.id) AS audit_entries
FROM ranked r
WHERE r.position > 1
ORDER BY r.job_id, r.created_at, r.id;
```

Inspect the actual target schema for additional foreign keys or consumers as
well. A clean fresh database test proves migration execution, not that deleting
production duplicates is acceptable.

## Migration 014 and rollback limits

Migration 014 repairs legacy `eval_log` string IDs to UUIDs and recreates the job
foreign key. Check for invalid UUID values and orphaned job references before
upgrading a legacy database. It leaves an already UUID-shaped table unchanged.

Migration 013's downgrade only drops the unique index. It cannot restore deleted
records, embeddings, or validation errors. Migration 014's downgrade is a no-op.
Redeploying an older application image also does not restore data. Recovery from
an unacceptable data change requires the approved backup/restore plan and must
account for writes since the backup.

Because 014 inspects the live schema, an offline `alembic upgrade head --sql`
render is not sufficient validation of this chain. Use a restored disposable
PostgreSQL database for the migration rehearsal.
