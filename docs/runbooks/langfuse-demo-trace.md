# Langfuse live demo trace (human gate)

Instrumentation is already on main (`app/observability.py`, `worker/tasks.py`). Live stranger traces need secrets on the deployed demo.

## Render (API + worker)

1. Open the DocExtract API and worker services in the Render dashboard.
2. Set (do not commit these values):
   - `LANGFUSE_ENABLED=true`
   - `LANGFUSE_PUBLIC_KEY=pk-lf-...`
   - `LANGFUSE_SECRET_KEY=sk-lf-...`
   - `LANGFUSE_HOST=https://cloud.langfuse.com` (or your host)
3. Redeploy API and worker so env vars load.
4. Upload one sample document through the live demo or API.
5. Confirm a `process_document` (or generation) span appears in the Langfuse project.
6. Optionally paste a **public** trace URL into the README only after verifying it loads in a private browser window.

## Local smoke

```bash
set -a && source .env && set +a
python scripts/langfuse_demo.py   # if present
```

## Accept criteria

- Stranger click → extraction job → visible Langfuse trace for that request.
- No canned/screenshot-only claim without a real project trace.
