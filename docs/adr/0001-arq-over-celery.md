# ADR-0001: ARQ over Celery for Async Job Queue

**Status**: Accepted
**Date**: 2026-01

## Context

DocExtract needs a background job queue for document processing. Its async services wait on storage, model APIs and PostgreSQL, alongside local parsing and validation work.

## Decision

Use ARQ (async job queue) over Celery for background document processing.

## Consequences

**Why:** ARQ provides an asyncio worker interface that fits the application's existing async services. [WorkerSettings](../../worker/main.py) registers document processing and extraction judging without introducing another task framework.

**Evidence limit:** No committed comparative ARQ/Celery benchmark establishes throughput or latency differences. The [Locust test](../../tests/load/locustfile.py) exercises API requests, including accepted uploads; it does not measure completed extraction throughput or provide a Celery comparator. The [metrics ledger](../portfolio-metrics.yaml) labels extraction latency as modeled.

**Scheduling:** The worker uses native ARQ cron to run stale-job recovery every ten minutes. Extraction judging is separately enqueued from the document-processing path. Neither behavior requires an external cron service in the current configuration.

**Tradeoff:** Queue storage, job execution and database state remain separate failure boundaries. ARQ's [pessimistic execution and retry semantics](https://arq-docs.helpmanual.io/#retrying-jobs-and-cancellation) require handlers to tolerate repeated delivery. The [redelivery test](../../tests/integration/test_pg_redelivery.py) checks the PostgreSQL lock and terminal-result behavior; it does not prove worker cancellation or automatic retries.

**Why not add graph orchestration?** The current pipeline is orchestrated by direct async calls. Adding a graph framework would introduce another execution abstraction. This decision does not establish a performance advantage over LangGraph or Celery.
