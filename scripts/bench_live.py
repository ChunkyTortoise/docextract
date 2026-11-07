"""Measure end-to-end latency and cost per document against a deployed DocExtract.

Unlike scripts/benchmark.py (which calls the extractor in-process), this goes
through the real deployment: HTTP upload -> S3 -> ARQ queue -> worker -> LLM ->
Postgres, and times each document from upload until its job reaches a terminal
state. Documents run one at a time, so the numbers describe a single user's
request, not contended throughput.

Cost per document has two parts:
  - LLM: the deployment's own token traces, read from /api/v1/metrics/llm before
    and after the run (delta), so per-model token counts can be re-priced.
  - Infrastructure: the hourly stack cost you pass in (docs/aws-deploy.md) times
    the run's wall-clock hours, divided by documents. This is the marginal cost
    of the run, not an amortized share of an always-on deployment.

Run (from your machine, after scripts/aws/deploy.sh seed-key):
    export DOCEXTRACT_API_KEY="$(cat ~/.docextract-aws/bench_api_key)"
    python scripts/bench_live.py --base-url http://<alb-dns> --runs 10
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
DEFAULT_FILES = [
    REPO / "tests" / "fixtures" / "sample_invoice.pdf",
    REPO / "tests" / "fixtures" / "sample_receipt.png",
]
TERMINAL = {"completed", "needs_review", "failed", "cancelled"}
SUCCESS = {"completed", "needs_review"}
# Additive per-model fields of /api/v1/metrics/llm (averages can't be differenced)
COUNTERS = ("call_count", "input_tokens", "output_tokens", "estimated_cost_usd")


def pct(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile (same convention as scripts/benchmark.py)."""
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)


def llm_snapshot(client: httpx.Client) -> dict:
    r = client.get("/api/v1/metrics/llm", params={"hours": 24})
    r.raise_for_status()
    return r.json()


def llm_delta(before: dict, after: dict) -> dict:
    def by_model(snap: dict) -> dict[str, dict]:
        return {m.get("model", "?"): m for m in snap.get("by_model", [])}

    b, a = by_model(before), by_model(after)
    models = {}
    for name, m in a.items():
        prev = b.get(name, {})
        delta = {k: (m.get(k) or 0) - (prev.get(k) or 0) for k in COUNTERS}
        if any(delta.values()):
            models[name] = delta
    return {
        "calls": after["total_calls"] - before["total_calls"],
        "input_tokens": after["total_input_tokens"] - before["total_input_tokens"],
        "output_tokens": after["total_output_tokens"] - before["total_output_tokens"],
        "cost_usd_app_price_table": round(after["total_cost_usd"] - before["total_cost_usd"], 6),
        "by_model": models,
    }


def run_one(client: httpx.Client, path: Path, timeout_s: float, poll_s: float) -> dict:
    t0 = time.perf_counter()
    with path.open("rb") as fh:
        r = client.post(
            "/api/v1/documents/upload",
            params={"force": "true"},  # same bytes each run: skip duplicate detection
            files={"file": (path.name, fh)},
        )
    upload_ms = (time.perf_counter() - t0) * 1000
    if r.status_code not in (200, 202):
        return {"file": path.name, "status": f"upload_http_{r.status_code}", "error": r.text[:200]}
    job_id = r.json()["job_id"]

    status, job = "queued", {}
    while time.perf_counter() - t0 < timeout_s:
        time.sleep(poll_s)
        jr = client.get(f"/api/v1/jobs/{job_id}")
        if jr.status_code != 200:
            continue
        job = jr.json()
        status = job["status"]
        if status in TERMINAL:
            break
    else:
        status = "timeout"

    return {
        "file": path.name,
        "job_id": job_id,
        "status": status,
        "upload_ms": round(upload_ms, 1),
        "end_to_end_ms": round((time.perf_counter() - t0) * 1000, 1),
        "server_processing_ms": job.get("processing_time_ms"),
        "error": job.get("error_message"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base-url", required=True, help="e.g. http://<alb-dns-name>")
    ap.add_argument("--files", nargs="*", type=Path, default=DEFAULT_FILES)
    ap.add_argument("--runs", type=int, default=10, help="passes over --files (default 10)")
    ap.add_argument("--infra-hourly-usd", type=float, default=None,
                    help="stack cost per hour from docs/aws-deploy.md, for infra cost per doc")
    ap.add_argument("--timeout", type=float, default=300.0, help="per-document timeout, seconds")
    ap.add_argument("--poll", type=float, default=0.5, help="job poll interval, seconds")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    api_key = os.environ.get("DOCEXTRACT_API_KEY")
    if not api_key:
        print("Set DOCEXTRACT_API_KEY (scripts/aws/deploy.sh seed-key saves one).", file=sys.stderr)
        return 2
    for f in args.files:
        if not f.is_file():
            print(f"missing file: {f}", file=sys.stderr)
            return 2

    client = httpx.Client(base_url=args.base_url.rstrip("/"), headers={"X-API-Key": api_key}, timeout=30)
    health = client.get("/api/v1/health").json()
    print(f"health: {health}")
    before = llm_snapshot(client)

    started = time.perf_counter()
    rows = []
    total = args.runs * len(args.files)
    for i in range(args.runs):
        for f in args.files:
            row = run_one(client, f, args.timeout, args.poll)
            rows.append(row)
            print(f"[{len(rows):>3}/{total}] {row['file']:<22} {row['status']:<14} {row.get('end_to_end_ms', '-')} ms")
    wall_h = (time.perf_counter() - started) / 3600

    after = llm_snapshot(client)
    ok = [r for r in rows if r["status"] in SUCCESS]
    e2e = [r["end_to_end_ms"] for r in ok]
    server = [r["server_processing_ms"] for r in ok if r.get("server_processing_ms") is not None]
    llm = llm_delta(before, after)

    summary = {
        "timestamp": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "deployment_health": health,
        "documents": len(rows),
        "succeeded": len(ok),
        "failed": [{"file": r["file"], "status": r["status"], "error": r.get("error")} for r in rows if r not in ok],
        "end_to_end_ms_p50": pct(e2e, 0.50),
        "end_to_end_ms_p95": pct(e2e, 0.95),
        "end_to_end_ms_mean": round(statistics.mean(e2e), 1) if e2e else None,
        "server_processing_ms_p50": pct(server, 0.50),
        "server_processing_ms_p95": pct(server, 0.95),
        "run_wall_hours": round(wall_h, 4),
        "llm": llm,
        "llm_cost_per_doc_usd_app_price_table": round(llm["cost_usd_app_price_table"] / len(ok), 6) if ok else None,
        "infra_hourly_usd": args.infra_hourly_usd,
        "infra_cost_per_doc_usd_run_marginal": (
            round(args.infra_hourly_usd * wall_h / len(ok), 6) if ok and args.infra_hourly_usd else None
        ),
        "note": "LLM cost uses the app's COST_PER_1M table; re-price llm.by_model tokens at current list prices before publishing.",
        "per_document": rows,
    }

    out = args.out or REPO / "eval_artifacts" / f"bench_live_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: summary[k] for k in (
        "documents", "succeeded", "end_to_end_ms_p50", "end_to_end_ms_p95",
        "llm_cost_per_doc_usd_app_price_table", "infra_cost_per_doc_usd_run_marginal")}, indent=2))
    print(f"wrote {out.relative_to(REPO) if out.is_relative_to(REPO) else out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
