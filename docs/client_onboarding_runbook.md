# DocExtract AI — Client Onboarding Runbook

## Prerequisites

- Render account (free tier works for demo; standard plan recommended for production)
- PostgreSQL connection string (Render managed DB, Supabase, or your own)
- Redis connection string (Render managed KV, Upstash, or your own)
- Anthropic API key (for Claude extraction)
- Gemini API key (for embedding — `text-embedding-004`)

---

## 1. Deploy via render.yaml

Click **New → Blueprint** in your Render dashboard and point it at this repo. Render reads `render.yaml` and provisions:

- `docextract-api` — FastAPI web service
- `docextract-worker` — ARQ background worker
- `docextract-frontend` — Streamlit dashboard
- `docextract-redis` — Redis KV store
- `docextract-db` — PostgreSQL 16 database

Set these env vars via the Render dashboard after the initial deploy:

| Key | Value |
|-----|-------|
| `ANTHROPIC_API_KEY` | `sk-ant-...` |
| `GEMINI_API_KEY` | `AI...` |

All other vars are auto-wired from Render's service graph.

---

## 2. Run migrations

Migrations run automatically in `buildCommand`. To run manually:

```bash
alembic upgrade head
```

Three migrations apply:
- `001_initial_schema` — core tables
- `002_pgvector_extension` — embedding column (uses `Text`, not `Vector`)
- `003_review_queue` — review lifecycle columns

---

## 3. Create an API key

```bash
export API_URL=https://docextract-api.onrender.com

curl -X POST "$API_URL/api/v1/api-keys" \
  -H "Content-Type: application/json" \
  -d '{"name": "client-prod", "role": "operator"}'
```

Save the returned `key` value — it is shown only once.

For read-only integrations (dashboards, reporting), use `"role": "viewer"`.

---

## 4. Upload your first document

```bash
export KEY=your-api-key-here

curl -X POST "$API_URL/api/v1/documents/upload" \
  -H "X-API-Key: $KEY" \
  -F "file=@invoice.pdf;type=application/pdf" \
  -F "priority=standard"
```

The response includes `job_id`. Track processing via SSE:

```bash
curl -N -H "X-API-Key: $KEY" "$API_URL/api/v1/jobs/$JOB_ID/events"
```

When `status=completed`, fetch the extracted record:

```bash
curl -H "X-API-Key: $KEY" "$API_URL/api/v1/records?job_id=$JOB_ID"
```

---

## 5. Configure webhooks

To receive async notifications on job completion:

```bash
curl -X POST "$API_URL/api/v1/documents/upload" \
  -H "X-API-Key: $KEY" \
  -F "file=@invoice.pdf" \
  -F "webhook_url=https://your-server.com/docextract/webhook"
```

Webhook payloads are POST requests with `Content-Type: application/json`. Test your receiver:

```bash
curl -X POST "$API_URL/api/v1/webhooks/test" \
  -H "X-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://your-server.com/docextract/webhook"}'
```

---

## 6. Enable demo mode (optional)

Add `DEMO_MODE=true` to the API service env vars. This enables the demo page at `/demo` and accepts the key `demo-key-docextract-2026` for read-only access.

Run the seed script to populate demo data:

```bash
python -m scripts.seed_demo
```

---

## 7. Run the smoke test

```bash
export DOCEXTRACT_API_URL=https://docextract-api.onrender.com
export DOCEXTRACT_API_KEY=your-api-key-here
bash scripts/smoke_productization.sh
```

All 7 endpoints should return 2xx. If any fail, check Render logs.
