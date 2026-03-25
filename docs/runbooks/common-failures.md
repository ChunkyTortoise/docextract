# Runbook: Common Failure Modes

## 1. Circuit Breaker Stuck OPEN (Model Provider Down)

**Symptoms**: Extraction requests return fallback model results; `circuit_breaker_state` metric shows `OPEN` for > 2 minutes.

**Diagnosis**:
```bash
# Check circuit breaker state via metrics
curl -s http://localhost:8000/metrics | grep circuit_breaker

# Check Anthropic API status
curl -s https://status.anthropic.com/api/v2/status.json | jq '.status'
```

**Resolution**:
1. If provider is down: no action needed. Circuit breaker will auto-recover (HALF_OPEN -> CLOSED) once the provider responds successfully.
2. If provider is up but circuit remains open: check `CIRCUIT_BREAKER_RECOVERY_TIMEOUT` (default 60s). Restart API if stuck.
3. If fallback model is also failing: both circuits OPEN. Queue will back up. Pause ingestion until at least one model recovers.

**Prevention**: Monitor Anthropic status page. Configure Prometheus alert for `circuit_breaker_state == 2` (OPEN) for > 2 minutes.

---

## 2. Redis Connection Timeout

**Symptoms**: 500 errors on API requests; rate limiting fails open; SSE streaming stops; circuit breaker state lost.

**Diagnosis**:
```bash
# Test Redis connectivity
redis-cli -u $REDIS_URL ping

# Check connection pool
redis-cli -u $REDIS_URL info clients
```

**Resolution**:
1. Check Redis memory usage (`info memory`). If at max, evict keys or scale.
2. Check network connectivity between API and Redis.
3. If Redis is unrecoverable: API will function without rate limiting (fails open). Queue processing stops until Redis returns.

**Prevention**: Set `maxmemory-policy allkeys-lru` in Redis config. Monitor `redis_connected_clients` metric.

---

## 3. Database Connection Pool Exhaustion

**Symptoms**: Slow API responses; `OperationalError: QueuePool limit` in logs; extraction jobs hang.

**Diagnosis**:
```bash
# Check active connections
psql $DATABASE_URL -c "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database();"

# Check pool settings
grep POOL_SIZE .env
```

**Resolution**:
1. Check for long-running queries: `SELECT pid, now() - pg_stat_activity.query_start AS duration, query FROM pg_stat_activity WHERE state != 'idle' ORDER BY duration DESC;`
2. Kill stuck queries: `SELECT pg_terminate_backend(pid);`
3. Increase `POOL_SIZE` if consistently near limit (default: 5, recommended: 10-20 for production).

**Prevention**: Set `pool_pre_ping=True` in SQLAlchemy config (already enabled). Monitor connection count vs pool size.

---

## 4. Queue Backlog (ARQ Worker Lag)

**Symptoms**: Document processing delays; extraction jobs queued but not starting; `/api/v1/jobs` shows many `pending` jobs.

**Diagnosis**:
```bash
# Check queue depth
redis-cli -u $REDIS_URL llen arq:queue

# Check worker status
redis-cli -u $REDIS_URL keys "arq:worker:*"
```

**Resolution**:
1. Check if worker process is running. Restart if crashed.
2. If queue is deep: scale workers horizontally (K8s: increase replica count in `deploy/k8s/overlays/production/`).
3. If a single job is stuck: check for model timeout. Default `EXTRACTION_TIMEOUT=120s`.

**Prevention**: Alert on queue depth > 100. Auto-scale workers based on queue length in K8s HPA.

---

## 5. Vector Index Slow Query

**Symptoms**: Search requests take > 1s; pgvector HNSW index scan shows sequential scan in `EXPLAIN`.

**Diagnosis**:
```sql
-- Check index usage
EXPLAIN ANALYZE SELECT * FROM records ORDER BY embedding <=> $1 LIMIT 10;

-- Check index size
SELECT pg_size_pretty(pg_relation_size('records_embedding_idx'));
```

**Resolution**:
1. Verify HNSW index exists: `\d records` should show `records_embedding_idx`.
2. If index is missing: `CREATE INDEX records_embedding_idx ON records USING hnsw (embedding vector_cosine_ops);`
3. If index exists but not used: run `VACUUM ANALYZE records;` to update statistics.
4. If dataset grew significantly: consider increasing `m` and `ef_construction` parameters.

**Prevention**: Monitor search latency p95. Rebuild index after bulk ingestion.

---

## 6. OTEL Exporter Connection Failure

**Symptoms**: Traces not appearing in Jaeger/Tempo; `OTEL_ENABLED=true` but no trace data.

**Diagnosis**:
```bash
# Check OTEL endpoint
curl -s http://localhost:4317/health  # gRPC
curl -s http://localhost:4318/health  # HTTP

# Check env
echo $OTEL_EXPORTER_OTLP_ENDPOINT
```

**Resolution**:
1. OTEL failure is non-blocking by design. API continues operating normally.
2. Check that Jaeger/Tempo container is running: `docker-compose -f docker-compose.observability.yml ps`
3. Verify `OTEL_EXPORTER_OTLP_ENDPOINT` points to the correct host (default: `http://localhost:4317`).

**Prevention**: OTEL is feature-flagged (`OTEL_ENABLED=false` by default). Failures are logged but do not affect extraction pipeline.

---

## Escalation Path

1. **Automated recovery**: Circuit breaker, queue retry (3 attempts), Redis reconnect
2. **Manual intervention**: Restart service, scale workers, kill stuck queries
3. **Architecture change needed**: If failures are systemic (e.g., model provider consistently slow), consider adjusting circuit breaker thresholds or switching primary/fallback model ordering
