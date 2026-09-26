# DocExtract AI - Release Checklist

## Pre-Release

- [ ] All tests pass: `pytest tests/ --no-cov -q`
- [ ] Ruff clean: `ruff check app worker tests`
- [ ] No secrets committed (`git grep -r "sk-ant-\|AIza"` returns empty)
- [ ] `requirements_full.txt` is up-to-date (`pip freeze > requirements_full.txt`)
- [ ] Version bump in `app/main.py` → `FastAPI(version="x.y.z")`
- [ ] `render.yaml` migrations command correct: `alembic upgrade head && python -m scripts.seed_demo` (demo) or `alembic upgrade head` (prod)
- [ ] New migrations reviewed for safety (no DROP TABLE, no NOT NULL without DEFAULT on large tables)

## Migration Safety Check

- [ ] `alembic history` shows expected chain
- [ ] Rehearsed the migration on a restored disposable PostgreSQL database (014 requires online schema inspection)
- [ ] Reviewed [reconciliation release gate](reconciliation-release.md), duplicate dependencies, backups, and migration-specific rollback limits
- [ ] Existing application database migration and deployment explicitly approved

## Deploy

1. Confirm the live Render auto-deploy branch/settings and complete the migration gate before an approved merge to `main`
2. Monitor Render deploy logs - watch for `Alembic upgrade complete` and `Application startup complete`
3. Render runs `buildCommand` → `preDeployCommand` (migrations) → `startCommand` in sequence

## Post-Deploy Verification

- [ ] `GET /api/v1/health` returns `{"status": "healthy"}`
- [ ] Run smoke test:

```bash
export DOCEXTRACT_API_URL=http://localhost:8000
export DOCEXTRACT_API_KEY=<prod-key>
bash scripts/smoke_productization.sh
```

- [ ] `GET /demo` renders the demo page
- [ ] Upload a test document end-to-end
- [ ] Check container logs for errors in first 5 minutes post-deploy (`docker compose logs`)

## Rollback Procedure

If deploy fails:

1. In Render dashboard → Service → **Deploys** tab → click previous deploy → **Redeploy**
2. Use the approved migration-specific recovery plan. Downgrading 013 does not restore deleted data, and 014's downgrade is a no-op; restore from backup when required.
3. Announce rollback in relevant Slack channel with root cause

## Version Tagging

```bash
git tag v1.x.y
git push origin v1.x.y
```
