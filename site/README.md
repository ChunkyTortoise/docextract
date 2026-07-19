# Marketing site (`site/`)

Static front door for DocExtract AI — plain HTML + CSS, no build step required.

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
