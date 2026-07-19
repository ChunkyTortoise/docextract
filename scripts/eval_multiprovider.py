#!/usr/bin/env python3
"""
Multi-provider eval runner — runs the identical LLM-judge suite per provider.

Eval-time only: never wired to stranger-facing demo clicks. Skips providers
whose API keys are absent instead of failing CI.

Usage:
  python scripts/eval_multiprovider.py
  python scripts/eval_multiprovider.py --providers anthropic openai
  python scripts/eval_multiprovider.py --out eval_artifacts/multiprovider_panel.json

Output JSON (multiprovider_panel.json):
  {
    "timestamp": "...",
    "golden": "evals/golden_set.jsonl",
    "providers": {
      "anthropic": {
        "model": "claude-haiku-4-5-20251001",
        "task_success_rate": 0.94,
        "latency_ms": {"p50": 1200, "p95": 3400},
        "cost_per_task_usd": null,
        "artifact": "eval_artifacts/llm_judge_anthropic.json"
      },
      ...
    },
    "skipped": ["openai"]
  }

cost_per_task_usd is null until populated from measured token usage in a future
telemetry pass — do not invent numbers.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Import sibling eval helpers (scripts/ is not a package)
sys.path.insert(0, str(REPO_ROOT))

from scripts.eval_llm_judge import (  # noqa: E402
    DEFAULT_JUDGE_MODELS,
    PROVIDER_CHOICES,
    PROVIDER_ENV_KEYS,
    load_jsonl,
    run_judge,
    summarize,
)


def _provider_available(provider: str) -> bool:
    return bool(os.environ.get(PROVIDER_ENV_KEYS[provider]))


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 1)
    ranked = sorted(values)
    idx = (len(ranked) - 1) * pct
    lower = int(idx)
    upper = min(lower + 1, len(ranked) - 1)
    weight = idx - lower
    return round(ranked[lower] * (1 - weight) + ranked[upper] * weight, 1)


async def _run_provider(
    provider: str,
    cases: list[dict],
    model: str | None,
    n_samples: int,
    concurrency: int,
    out_dir: Path,
) -> tuple[str, dict[str, Any]]:
    started = time.perf_counter()
    per_case_latencies_ms: list[float] = []

    async def _timed_run() -> list[dict]:
        # run_judge batches internally; wall-clock per provider is the panel signal
        return await run_judge(
            cases,
            provider=provider,
            model=model,
            concurrency=concurrency,
            n_samples=n_samples,
        )

    results = await _timed_run()
    elapsed_ms = (time.perf_counter() - started) * 1000
    per_case_latencies_ms = [elapsed_ms / len(cases)] * len(cases) if cases else []

    resolved_model = model or DEFAULT_JUDGE_MODELS[provider]
    summary = summarize(results, provider=provider, model=resolved_model)

    artifact = out_dir / f"llm_judge_{provider}.json"
    artifact.write_text(json.dumps(summary, indent=2))

    panel_entry: dict[str, Any] = {
        "model": resolved_model,
        "task_success_rate": summary["pass_rate"],
        "case_count": summary["case_count"],
        "pass_count": summary["pass_count"],
        "avg_scores": summary["avg_scores"],
        "latency_ms": {
            "p50": _percentile(per_case_latencies_ms, 0.50),
            "p95": _percentile(per_case_latencies_ms, 0.95),
            "wall_clock_total_ms": round(elapsed_ms, 1),
        },
        "cost_per_task_usd": None,
        "artifact": str(artifact.relative_to(REPO_ROOT)),
    }
    return provider, panel_entry


async def run_multiprovider(
    providers: list[str],
    cases: list[dict],
    models: dict[str, str | None],
    n_samples: int,
    concurrency: int,
    out_dir: Path,
) -> dict[str, Any]:
    available = [p for p in providers if _provider_available(p)]
    skipped = [p for p in providers if p not in available]

    if skipped:
        for p in skipped:
            print(f"Skipping {p}: {PROVIDER_ENV_KEYS[p]} not set", file=sys.stderr)

    if not available:
        print("ERROR: no provider API keys available", file=sys.stderr)
        sys.exit(1)

    provider_results: dict[str, dict[str, Any]] = {}
    for provider in available:
        print(f"\n=== Provider: {provider} ===", file=sys.stderr)
        _, entry = await _run_provider(
            provider,
            cases,
            models.get(provider),
            n_samples,
            concurrency,
            out_dir,
        )
        provider_results[provider] = entry
        print(
            f"  task_success_rate={entry['task_success_rate']:.4f} "
            f"wall_clock_ms={entry['latency_ms']['wall_clock_total_ms']}",
            file=sys.stderr,
        )

    return {
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "case_count": len(cases),
        "n_samples": n_samples,
        "providers": provider_results,
        "skipped": skipped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LLM-judge eval across multiple providers")
    parser.add_argument("--golden", type=Path, default=REPO_ROOT / "evals" / "golden_set.jsonl")
    parser.add_argument("--adv", action="store_true", help="Include adversarial set")
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=PROVIDER_CHOICES,
        default=list(PROVIDER_CHOICES),
        help="Providers to run (skips those without API keys)",
    )
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "eval_artifacts" / "multiprovider_panel.json")
    parser.add_argument("--n-samples", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        metavar="PROVIDER=MODEL",
        help="Per-provider model override, e.g. openai=gpt-4o-mini",
    )
    args = parser.parse_args()

    cases = load_jsonl(args.golden)
    if args.adv:
        adv_path = args.golden.parent / "adversarial_set.jsonl"
        if adv_path.exists():
            cases.extend(load_jsonl(adv_path))

    models: dict[str, str | None] = {p: None for p in args.providers}
    for item in args.model:
        if "=" not in item:
            print(f"WARNING: ignoring malformed --model {item!r} (expected PROVIDER=MODEL)", file=sys.stderr)
            continue
        prov, model_name = item.split("=", 1)
        if prov in models:
            models[prov] = model_name

    args.out.parent.mkdir(parents=True, exist_ok=True)
    panel = asyncio.run(
        run_multiprovider(
            args.providers,
            cases,
            models,
            args.n_samples,
            args.concurrency,
            args.out.parent,
        )
    )
    panel["golden"] = str(args.golden.relative_to(REPO_ROOT))
    args.out.write_text(json.dumps(panel, indent=2))

    print(f"\nMulti-provider panel written to {args.out}")
    for prov, entry in panel["providers"].items():
        lat = entry["latency_ms"]
        print(
            f"  {prov} ({entry['model']}): success={entry['task_success_rate']:.4f} "
            f"p50≈{lat['p50']}ms wall={lat['wall_clock_total_ms']}ms cost/task=n/a"
        )
    if panel["skipped"]:
        print(f"  skipped (no key): {', '.join(panel['skipped'])}")


if __name__ == "__main__":
    main()
