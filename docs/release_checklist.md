# DocExtract AI — Release Checklist

## Pre-Release

- [ ] All tests pass: `pytest tests/ --no-cov -q`
- [ ] Ruff clean: `ruff check app worker tests`
- [ ] No secrets committed (`git grep -r "sk-ant-\|AIza"` returns empty)
- [ ] `requirements.txt` is up-to-date (`pip freeze > requirements.txt`)
- [ ] Version bump in `app/main.py` → `FastAPI(version="x.y.z")`
- [ ] `render.yaml` migrations command correct: `alembic upgrade head && python -m scripts.seed_demo` (demo) or `alembic upgrade head` (prod)
- [ ] New migrations reviewed for safety (no DROP TABLE, no NOT NULL without DEFAULT on large tables)

## Migration Safety Check

- [ ] `alembic history` shows expected chain
- [ ] `alembic upgrade head --sql` reviewed (dry-run SQL output)
- [ ] Verified migration is reversible: `alembic downgrade -1` tested locally

## Deploy

1. Merge PR to `main` (Render auto-deploys on push to main)
2. Monitor Render deploy logs — watch for `Alembic upgrade complete` and `Application startup complete`
3. Render runs `buildCommand` → `startCommand` in sequence

## Post-Deploy Verification

- [ ] `GET /api/v1/health` returns `{"status": "healthy"}`
- [ ] Run smoke test:

```bash
export DOCEXTRACT_API_URL=https://docextract-api.onrender.com
export DOCEXTRACT_API_KEY=<prod-key>
bash scripts/smoke_productization.sh
```

- [ ] `GET /demo` renders the demo page
- [ ] Upload a test document end-to-end
- [ ] Check Render logs for errors in first 5 minutes post-deploy

## Rollback Procedure

If deploy fails:

1. In Render dashboard → Service → **Deploys** tab → click previous deploy → **Redeploy**
2. If migration broke the schema: `alembic downgrade -1` via Render shell or local env with prod DB URL
3. Announce rollback in relevant Slack channel with root cause

## Version Tagging

```bash
git tag v1.x.y
git push origin v1.x.y
```
