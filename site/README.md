# Project page (static preview, `site/`)

Static preview page for DocExtract AI. Not the live app. Plain HTML + CSS, no build step.

## Serve locally

From the repo root:

```bash
python -m http.server 4173 --directory site
```

Open http://localhost:4173

## Alternatives

Any static file server works, for example:

```bash
npx --yes serve site -p 4173
```

## Deploy

Upload the `site/` directory to any static host (GitHub Pages, Cloudflare Pages, S3 + CloudFront, etc.). No compile step.

## Content sources

Copy and metrics on the page mirror the README and `docs/portfolio-metrics.yaml`. Update those sources first, then refresh `site/index.html` if numbers or links change.

The hero proof image is `site/eval-proof.svg`, kept in lockstep with `docs/assets/eval-proof.svg`. The 1280×640 social card lives at `docs/assets/social-preview.svg`; it has not been uploaded to GitHub Settings.
