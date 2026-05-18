"""Portfolio benchmark: real F1 / latency / cost / straight-through over the 72-case corpus.

Every headline number in the README must trace to a reproducible measurement, not a
design-doc estimate. This driver runs the real two-pass extractor over the committed
corpus and reports:

  - extraction F1 (combined / golden / adversarial / per-doc-type) via the SAME
    weighted field scorer used by the 28-case baseline (`autoresearch.eval.score_extraction`)
  - end-to-end latency p50/p95 — wall-clock per document, measured sequentially so the
    numbers reflect a single user's request, not contended throughput
  - average cost/document — MEASURED: real input/output token counts captured per LLM
    call via the in-memory llm_tracer, priced with the in-repo pricing table
    (`app.services.cost_tracker`). Not modeled from a static cost doc.
  - straight-through rate — fraction of docs that needed neither a Pass-2 correction
    nor a self-reflection pass

Side effect: records `autoresearch/golden_responses/<id>.json` fixtures (raw + parsed)
so CI can replay the corpus deterministically with no API key. Scoring/pricing logic
is imported, never reimplemented.

Run:  .venv/bin/python scripts/benchmark.py            # full 72-case live run
      .venv/bin/python scripts/benchmark.py --limit 3  # smoke (first 3 cases)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _load_env() -> None:
    """Inject REPO/.env into os.environ so the run is cwd-independent.

    pydantic-settings resolves env_file relative to CWD; CI/background runners
    may start elsewhere. Does not override variables already set in the real env.
    """
    import os

    env = REPO / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        # Inject when missing OR present-but-empty (an empty exported var must
        # not shadow the real .env value); never clobber a real non-empty value.
        if k and v and not os.environ.get(k):
            os.environ[k] = v


_load_env()

from autoresearch.eval import score_extraction  # noqa: E402

DATASET = REPO / "autoresearch" / "eval_dataset_72.json"
FIXTURE_DIR = REPO / "autoresearch" / "golden_responses"
STAMP = datetime.now().strftime("%Y%m%d")
RUN_OUT = REPO / "autoresearch" / f"benchmark_{STAMP}.json"


def _weighted_f1(rows: list[dict]) -> float:
    tw = sum(r["weight"] for r in rows)
    return sum(r["score"] * r["weight"] for r in rows) / tw if tw else 0.0


async def _run_case(case: dict) -> dict:
    """Run one extraction sequentially, capturing measured cost + wall latency."""
    import time

    from app.services.claude_extractor import extract
    from app.services.cost_tracker import COST_PER_1K_TOKENS, CostTracker
    from app.services.llm_tracer import clear_in_memory_traces, get_in_memory_traces

    clear_in_memory_traces()
    tracker = CostTracker()

    t0 = time.perf_counter()
    try:
        # db=None -> traces go in-memory, active-learning few-shot is skipped
        result = await extract(case["input_text"], case["doc_type"])
        extracted = result.data or {}
        model = getattr(result, "model_used", "") or ""
        raw = getattr(result, "raw_response", "") or ""
        corrections = bool(getattr(result, "corrections_applied", False))
        reflection = bool(getattr(result, "reflection_applied", False))
        err = None
    except Exception as e:  # record, never abort the sweep
        extracted, model, raw, corrections, reflection, err = {}, "", "", False, False, f"{type(e).__name__}: {e}"
    wall_ms = (time.perf_counter() - t0) * 1000.0

    cost_usd = 0.0
    priced_calls = 0
    for tr in get_in_memory_traces():
        it, ot, m = tr.get("input_tokens"), tr.get("output_tokens"), tr.get("model")
        if it is None or ot is None or m not in COST_PER_1K_TOKENS:
            continue
        rc = tracker.compute_cost(m, it, ot, tr.get("operation", "extract"), float(tr.get("latency_ms") or 0))
        cost_usd += float(rc.total_cost_usd)
        priced_calls += 1

    score = score_extraction(extracted, case["expected"], case["critical_fields"]) if not err else 0.0
    straight_through = (not err) and (not corrections) and (not reflection)

    if not err:
        (FIXTURE_DIR / f"{case['id']}.json").write_text(
            json.dumps(
                {
                    "case_id": case["id"],
                    "model": model,
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "raw_response": raw,
                    "parsed_extraction": extracted,
                },
                indent=2,
            )
        )

    return {
        "id": case["id"],
        "split": case["split"],
        "doc_type": case["doc_type"],
        "weight": case["weight"],
        "score": score,
        "model": model,
        "latency_ms": round(wall_ms, 1),
        "cost_usd": round(cost_usd, 6),
        "priced_calls": priced_calls,
        "corrections_applied": corrections,
        "reflection_applied": reflection,
        "straight_through": straight_through,
        "error": err,
    }


async def main(limit: int | None) -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    dataset = json.loads(DATASET.read_text())
    if limit:
        dataset = dataset[:limit]

    rows: list[dict] = []
    for i, case in enumerate(dataset, 1):
        r = await _run_case(case)
        rows.append(r)
        flag = r["error"] or f"F1={r['score']:.3f} {r['latency_ms']:.0f}ms ${r['cost_usd']:.4f}"
        print(f"[{i:>2}/{len(dataset)}] {r['id']:<28} {flag}")

    ok = [r for r in rows if not r["error"]]
    golden = [r for r in ok if r["split"] == "golden"]
    adv = [r for r in ok if r["split"] == "adversarial"]
    lat = sorted(r["latency_ms"] for r in ok)
    per_doc: dict[str, list[dict]] = defaultdict(list)
    for r in ok:
        per_doc[r["doc_type"]].append(r)

    def _pct(vals: list[float], q: float) -> float:
        if not vals:
            return 0.0
        idx = min(len(vals) - 1, int(round(q * (len(vals) - 1))))
        return round(vals[idx], 1)

    summary = {
        "timestamp": datetime.now(UTC).isoformat(),
        "dataset": str(DATASET.relative_to(REPO)),
        "case_count": len(rows),
        "scored_ok": len(ok),
        "errors": [r["id"] for r in rows if r["error"]],
        "extraction_f1_combined": round(_weighted_f1(ok), 4),
        "extraction_f1_golden": round(_weighted_f1(golden), 4),
        "extraction_f1_adversarial": round(_weighted_f1(adv), 4),
        "n_golden": len(golden),
        "n_adversarial": len(adv),
        "latency_ms_p50": _pct(lat, 0.50),
        "latency_ms_p95": _pct(lat, 0.95),
        "latency_s_p95": round(_pct(lat, 0.95) / 1000.0, 2),
        "avg_cost_per_doc_usd": round(statistics.mean([r["cost_usd"] for r in ok]), 4) if ok else 0.0,
        "straight_through_rate": round(sum(r["straight_through"] for r in ok) / len(ok), 4) if ok else 0.0,
        "per_doc_type": {
            dt: {"f1": round(_weighted_f1(rs), 4), "count": len(rs)}
            for dt, rs in sorted(per_doc.items())
        },
        "per_case": [
            {k: r[k] for k in ("id", "split", "doc_type", "score", "latency_ms", "cost_usd", "straight_through", "error")}
            for r in sorted(rows, key=lambda x: x["id"])
        ],
    }
    RUN_OUT.write_text(json.dumps(summary, indent=2))
    print("\n" + json.dumps({k: v for k, v in summary.items() if k != "per_case"}, indent=2))
    print(f"\nwrote {RUN_OUT.relative_to(REPO)}  +  {len(ok)} fixtures in autoresearch/golden_responses/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="run only the first N cases (smoke)")
    args = ap.parse_args()
    asyncio.run(main(args.limit))
