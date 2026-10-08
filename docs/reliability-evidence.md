# Reliability evidence, 2026-10-08

These are local engineering acceptance results. They establish the named database and queue behaviors, with explicit boundaries. They do not measure extraction quality, cost per document, production latency or deployment reliability.

## Failure, decision, result

| Observed failure | Repair and acceptance | Limit |
|---|---|---|
| A second worker could enter extraction for an in-flight job | Lock the job before inspecting its state, then reuse terminal results. One real PostgreSQL concurrency case passed. Removing that initial lock made the same test fail by entering extraction again. | Storage and Redis were controlled; this was not an ARQ test. |
| Fresh migrations stopped at an existing trigger in 007, then at the text-to-UUID foreign key in 012 | Correct the historical migration bodies and add an independent forward repair. Nine PostgreSQL schema cases passed. | Synthetic legacy shapes do not prove the original 012 could install. No production database was migrated. |
| Reraising an ordinary transient exception ended the queue job instead of scheduling another attempt | Use ARQ Retry for extraction attempts one and two, cap execution at three, and preserve the original error if final failure reporting also fails. Four real-queue cases passed; the focused worker suite passed 42 tests. | SQL and provider boundaries were controlled; startup, shutdown and cron hooks were omitted. |

The queue baseline failed three cases and passed the permanent-error control. After repair, it verified transient recovery, exhaustion at three attempts, one-attempt permanent failure, and rejection of an over-cap delivery. The separate final-reporting regression failed before repair when a secondary Redis exception replaced the original processing exception.

Permanent processing errors retain the existing contract: a returned failed-status payload, which ARQ records as a successful function return. Exhausted transient errors instead raise the original exception and produce a failed ARQ result. This distinction matters when interpreting queue counters.

## Provenance

PostgreSQL tests used PostgreSQL 17.8 and the schema source in [PR 71](https://github.com/ChunkyTortoise/docextract/pull/71), candidate `11173b6a5c91f29b18f743491ba1eddaad0a0ec6`. The redelivery repair was reviewed in [PR 70](https://github.com/ChunkyTortoise/docextract/pull/70), candidate `ede4ef98f60a9a793be5f4ee26206ea31bc40939`.

Queue tests used ARQ 0.26.1, Redis 8.6.1 and Python 3.12.7. The tested retry files have these SHA-256 values:

```json
{
  "worker/tasks.py": "5d62735e5388a105924580f624a43a9956ee243e20e685fe22b958bf2e4e7a3e",
  "worker/main.py": "7868001612623a747d59e17d6ad6026d5150e979fb063bd2dd62e45067ddb148",
  "tests/integration/test_arq_retries.py": "e32f4c96b5cfc72a0ba007799c56ca8e4142474b5cab4b96ecf34d7ddd3280a7"
}
```

Recorded summary excerpts:

```text
PostgreSQL schema acceptance: 9 passed in 12.58s
ARQ queue acceptance: 4 passed, 4 warnings in 4.31s
```

The queue warnings come from installed ARQ's deprecated Redis close call. Test elapsed times are runner durations, not extraction latency measurements. Disposable PostgreSQL and Redis processes were stopped afterward; their working directories and logs were retained locally. Redis used a private Unix socket with TCP and persistence disabled. No provider requests or shared service databases were used.

## Reproduce the boundaries

For fresh schema and synthetic legacy acceptance, follow the [schema repair runbook](runbooks/eval-log-schema-repair.md) to supply nine distinct empty local test databases and run [test_pg_schema_install.py](../tests/integration/test_pg_schema_install.py) with `--noconftest`. The test never creates or drops databases.

For the two-session lock check, provision the matching schema in a dedicated local `docextract_test_*` database, set `DOCEXTRACT_TEST_DATABASE_URL`, and run [test_pg_redelivery.py](../tests/integration/test_pg_redelivery.py) separately with `--noconftest`. Its module documents the setup limits.

For queue acceptance, use a host-owned disposable Redis Unix socket, with TCP disabled (`--port 0`) and persistence disabled (`--save '' --appendonly no`). Set `DOCEXTRACT_SOURCE` to the absolute checkout path and `ISOLATED_REDIS_SOCKET` to that socket. From a neutral directory without a `.env` file:

```bash
PYTHONPATH="$DOCEXTRACT_SOURCE" \
DATABASE_URL=postgresql+asyncpg://unused@127.0.0.1:1/docextract_test \
DOCEXTRACT_TEST_REDIS_SOCKET="$ISOLATED_REDIS_SOCKET" \
python -m pytest --noconftest -p no:cacheprovider -o addopts= \
"$DOCEXTRACT_SOURCE/tests/integration/test_arq_retries.py" -q
```

The queue test uses UUID-scoped jobs and queues, without FLUSHDB. It invokes the real extraction wrapper through ARQ but replaces SQL sessions, extraction and failure persistence with controlled test boundaries. It therefore does not establish production startup behavior, provider retries, cancellation recovery or a working full stack. The [failure runbook](runbooks/common-failures.md#escalation-path) describes the extraction retry policy.

These opt-in tests skip without their respective host-provisioned inputs. A green default CI run alone does not establish that the PostgreSQL or Redis acceptance cases ran.
