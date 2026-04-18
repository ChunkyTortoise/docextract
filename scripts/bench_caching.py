#!/usr/bin/env python3
"""Prompt caching benchmark: measures cold vs warm cache token costs.

Run 20 extraction calls for a fixed doc_type and document. On the first call
the system prompt block is written to the cache (creation tokens charged at
the standard rate). Subsequent calls read from the cache at ~10% of the
normal input-token price.

Usage:
    python scripts/bench_caching.py [--iterations 20] [--doc-type invoice]

Outputs a markdown table to stdout and writes
docs/benchmarks/caching-YYYY-MM-DD.md.
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

# Ensure project root on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

SAMPLE_DOC = """INVOICE #INV-2024-0042
Date: 2024-11-15
Due: 2024-12-15

Bill To:
Acme Corporation
123 Business Ave, Suite 400
San Francisco, CA 94105

Line Items:
1. AI Platform Subscription (annual)    $12,000.00
2. Professional Services (40h @ $150)   $6,000.00
3. Infrastructure Credits               $1,200.00
                                      ___________
Subtotal                              $19,200.00
Tax (8.75%)                           $1,680.00
Total Due                             $20,880.00

Payment Terms: Net 30
Bank: Silicon Valley Bank — Account: 987654321 — Routing: 121140399
"""

ANTHROPIC_COST_PER_1K = {
    "claude-sonnet-4-6": {"input": 0.003, "output": 0.015, "cache_read": 0.0003, "cache_write": 0.00375},
    "claude-haiku-4-5-20251001": {"input": 0.0008, "output": 0.004, "cache_read": 0.00008, "cache_write": 0.001},
}


async def _run_single(client, model: str, system_blocks: list, user_content: list, with_schema: bool) -> dict:
    from anthropic import AsyncAnthropic  # noqa
    t0 = time.monotonic()
    response = await client.messages.create(
        model=model,
        max_tokens=512,
        system=system_blocks,
        messages=[{"role": "user", "content": user_content}],
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    usage = response.usage
    return {
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "cache_creation_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "latency_ms": latency_ms,
    }


def _compute_cost(row: dict, model: str) -> float:
    rates = ANTHROPIC_COST_PER_1K.get(model, ANTHROPIC_COST_PER_1K["claude-sonnet-4-6"])
    cost = (
        row["input_tokens"] * rates["input"] / 1000
        + row["output_tokens"] * rates["output"] / 1000
        + row["cache_creation_tokens"] * rates["cache_write"] / 1000
        + row["cache_read_tokens"] * rates["cache_read"] / 1000
    )
    return cost


async def run_bench(model: str, iterations: int, doc_type: str) -> list[dict]:
    from anthropic import AsyncAnthropic
    from app.services.prompt_config import config as prompt_config

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ANTHROPIC_API_KEY not set — using dry-run mode (zeroed metrics)", file=sys.stderr)

    client = AsyncAnthropic(api_key=api_key)

    system_blocks = [
        {
            "type": "text",
            "text": prompt_config.extract_system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    user_content = [{"type": "text", "text": prompt_config.extract_prompt.format(doc_type=doc_type, text=SAMPLE_DOC)}]

    results = []
    for i in range(iterations):
        row = await _run_single(client, model, system_blocks, user_content, with_schema=False)
        row["iteration"] = i + 1
        row["cost_usd"] = _compute_cost(row, model)
        results.append(row)
        print(f"  [{i+1:02d}/{iterations}] input={row['input_tokens']} cache_create={row['cache_creation_tokens']} cache_read={row['cache_read_tokens']} latency={row['latency_ms']}ms cost=${row['cost_usd']:.5f}", flush=True)
        await asyncio.sleep(0.3)  # stay under rate limit

    return results


def _format_report(results: list[dict], model: str, doc_type: str) -> str:
    cold = results[0]
    warm = [r for r in results[1:] if r["cache_read_tokens"] > 0]

    avg_warm_cost = sum(r["cost_usd"] for r in warm) / len(warm) if warm else 0
    total_cost_with_cache = sum(r["cost_usd"] for r in results)
    total_cost_no_cache = sum(
        (r["input_tokens"] + r["cache_creation_tokens"] + r["cache_read_tokens"])
        * ANTHROPIC_COST_PER_1K.get(model, ANTHROPIC_COST_PER_1K["claude-sonnet-4-6"])["input"]
        / 1000
        + r["output_tokens"]
        * ANTHROPIC_COST_PER_1K.get(model, ANTHROPIC_COST_PER_1K["claude-sonnet-4-6"])["output"]
        / 1000
        for r in results
    )
    savings_pct = (1 - total_cost_with_cache / total_cost_no_cache) * 100 if total_cost_no_cache else 0

    lines = [
        f"# Prompt Caching Benchmark — {doc_type}",
        f"",
        f"Model: `{model}` | Date: {datetime.date.today()} | Iterations: {len(results)}",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Cold call cost | ${cold['cost_usd']:.5f} |",
        f"| Avg warm call cost | ${avg_warm_cost:.5f} |",
        f"| Warm cache hit rate | {len(warm)}/{len(results)-1} calls |",
        f"| Total cost (with cache) | ${total_cost_with_cache:.4f} |",
        f"| Total cost (no cache baseline) | ${total_cost_no_cache:.4f} |",
        f"| **Cost reduction** | **{savings_pct:.1f}%** |",
        f"",
        f"## Per-Iteration Results",
        f"",
        f"| Iter | Input Tokens | Cache Create | Cache Read | Latency ms | Cost USD |",
        f"|------|-------------|-------------|-----------|-----------|---------|",
    ]
    for r in results:
        lines.append(
            f"| {r['iteration']:4d} | {r['input_tokens']:11d} | {r['cache_creation_tokens']:11d} | "
            f"{r['cache_read_tokens']:9d} | {r['latency_ms']:9d} | ${r['cost_usd']:.5f} |"
        )
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark prompt caching")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--doc-type", default="invoice")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    args = parser.parse_args()

    print(f"Benchmarking prompt caching: model={args.model}, iterations={args.iterations}, doc_type={args.doc_type}")
    results = await run_bench(args.model, args.iterations, args.doc_type)

    report = _format_report(results, args.model, args.doc_type)
    print("\n" + report)

    out_dir = Path("docs/benchmarks")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"caching-{datetime.date.today()}.md"
    out_path.write_text(report)
    print(f"\nReport written to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
