# DocExtract API Reference — Productization Endpoints

Base URL: `http://localhost:8000/api/v1` (self-hosted via `docker compose up`)

All endpoints require `X-API-Key` header unless noted.

---

## Demo

### `GET /demo` _(public)_

Returns the self-contained demo HTML page for portfolio visitors.

**No auth required.**

```bash
curl http://localhost:8000/demo
```

---

## Review Queue

### `GET /api/v1/review/items`

List records in the review queue.

**Role required:** `operator`

Query params: `status`, `assignee`, `doc_type`, `page`, `page_size`

```bash
curl -H "X-API-Key: $KEY" "$BASE/review/items?status=pending_review"
```

**Response:**
```json
{
  "items": [
    {
      "id": "uuid",
      "document_type": "vendor_invoice",
      "status": "pending_review",
      "confidence_score": 0.65,
      "created_at": "2026-03-18T10:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "has_next": false
}
```

### `POST /api/v1/review/items/{id}/claim`

Claim a review item (optimistic concurrency — 409 if already claimed).

**Role required:** `operator`

```bash
curl -X POST -H "X-API-Key: $KEY" "$BASE/review/items/$ITEM_ID/claim"
```

**Response:** `{"status": "claimed", "item_id": "uuid", "assignee": "key-uuid"}`

### `POST /api/v1/review/items/{id}/approve`

Approve a claimed item.

**Role required:** `operator`

```bash
curl -X POST -H "X-API-Key: $KEY" "$BASE/review/items/$ITEM_ID/approve"
```

### `POST /api/v1/review/items/{id}/correct`

Submit corrections for a claimed item.

**Role required:** `operator`

```bash
curl -X POST -H "X-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"corrections": {"vendor_name": "ABC Corp"}, "reviewer_notes": "Fixed name"}' \
  "$BASE/review/items/$ITEM_ID/correct"
```

### `GET /api/v1/review/metrics`

SLA and queue metrics.

**Role required:** `operator`

Query params: `stale_after_hours` (default 24, range 1–168)

```bash
curl -H "X-API-Key: $KEY" "$BASE/review/metrics?stale_after_hours=24"
```

**Response:**
```json
{
  "queue": {"pending": 5, "claimed": 2, "total_open": 7, "stale": 1},
  "throughput": {"reviewed_last_24h": 12, "avg_time_to_review_seconds": 180.5},
  "sla": {"stale_after_hours": 24, "breach_rate": 0.1429, "escalation_item_ids": ["uuid"]}
}
```

---

## ROI

### `GET /api/v1/roi/summary`

Aggregated ROI KPIs for a date range (default: last 30 days).

**Role required:** `viewer`

Query params: `date_from`, `date_to` (ISO 8601)

```bash
curl -H "X-API-Key: $KEY" "$BASE/roi/summary"
```

**Response:**
```json
{
  "from": "2026-02-17T00:00:00Z",
  "to": "2026-03-18T00:00:00Z",
  "kpis": {
    "jobs_total": 42,
    "jobs_completed": 39,
    "records_total": 156,
    "records_reviewed": 12,
    "avg_confidence": 0.874,
    "avg_processing_indicator": 1234.5,
    "estimated_minutes_saved": 312.0,
    "estimated_dollars_saved": 182.0,
    "estimated_run_cost": 5.04,
    "net_value": 176.96
  }
}
```

### `GET /api/v1/roi/trends`

ROI broken down by weekly or monthly buckets.

**Role required:** `viewer`

Query params: `interval` (`week` | `month`), `date_from`, `date_to`

```bash
curl -H "X-API-Key: $KEY" "$BASE/roi/trends?interval=week"
```

**Response:**
```json
{
  "interval": "week",
  "from": "2026-02-17T00:00:00Z",
  "to": "2026-03-18T00:00:00Z",
  "points": [
    {
      "bucket_start": "2026-02-17T00:00:00Z",
      "bucket_end": "2026-02-24T00:00:00Z",
      "jobs_completed": 10,
      "dollars_saved": 46.67,
      "net_value": 45.47
    }
  ]
}
```

---

## Reports

### `POST /api/v1/reports/generate`

Generate a JSON or HTML executive report.

**Role required:** `operator`

```bash
curl -X POST -H "X-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"format": "json"}' \
  "$BASE/reports/generate"
```

**Response:** `{"report_id": "uuid", "files": ["storage/reports/uuid.json"], "status": "generated"}`

### `GET /api/v1/reports`

List generated reports.

**Role required:** `viewer`

```bash
curl -H "X-API-Key: $KEY" "$BASE/reports"
```

### `GET /api/v1/reports/{report_id}`

Retrieve a specific report with artifact content.

**Role required:** `viewer`

```bash
curl -H "X-API-Key: $KEY" "$BASE/reports/$REPORT_ID"
```
