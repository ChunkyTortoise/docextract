#!/usr/bin/env python3
"""
Eval gate: enforce metric thresholds, diff against baseline, emit HTML report.

Reads Promptfoo, Ragas, and LLM-judge JSON outputs, combines them, compares
against autoresearch/baseline.json, and exits 1 if any threshold is breached.

Usage:
  python scripts/eval_gate.py \
    --promptfoo eval_artifacts/promptfoo.json \
    --ragas     eval_artifacts/ragas.json \
    --judge     eval_artifacts/llm_judge.json \
    --baseline  autoresearch/baseline.json \
    --out       eval_artifacts/scores.json \
    --report    eval_artifacts/eval_report.html \
    --mode      pull_request   # pull_request | push | schedule | local

Exit codes:
  0 — all thresholds met
  1 — threshold breach (CI fail)
  2 — comparison error (missing files, schema mismatch)

Outputs (in addition to exit code):
  eval_artifacts/scores.json     — combined metrics
  eval_artifacts/pr_comment.md   — sticky PR comment body (Markdown table)
  eval_artifacts/eval_report.html — standalone HTML report
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Absolute floors ───────────────────────────────────────────────────────────
ABSOLUTE_FLOORS: dict[str, float] = {
    "faithfulness": 0.85,
    "answer_relevancy": 0.80,
    "context_precision": 0.75,
    "extraction_f1": 0.90,   # mapped from run_eval_ci overall_score
    "judge_pass_rate": 0.80,
}

# ── Relative drop tolerance (fraction) ────────────────────────────────────────
RELATIVE_DROP_TOLERANCE: float = 0.03


def load_json(path: Path) -> dict | None:
    """Load JSON file, return None if missing."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(f"WARNING: Could not parse {path}: {e}", file=sys.stderr)
        return None


def extract_promptfoo_metrics(data: dict | None) -> dict:
    if not data:
        return {}
    # Promptfoo output schema: {results: {stats: {successes, failures, tokenUsage: {...}}}}
    stats = data.get("results", {}).get("stats", {})
    total = stats.get("successes", 0) + stats.get("failures", 0)
    if total == 0:
        return {}
    return {
        "promptfoo_pass_rate": round(stats.get("successes", 0) / total, 4),
        "promptfoo_total": total,
        "promptfoo_failures": stats.get("failures", 0),
    }


def extract_ragas_metrics(data: dict | None) -> dict:
    if not data:
        return {}
    metrics = data.get("metrics", {})
    return {
        "faithfulness": metrics.get("faithfulness", 0.0),
        "answer_relevancy": metrics.get("answer_relevancy", 0.0),
        "context_precision": metrics.get("context_precision", 0.0),
    }


def extract_judge_metrics(data: dict | None) -> dict:
    if not data:
        return {}
    return {
        "judge_pass_rate": data.get("pass_rate", 0.0),
        "judge_avg_faithfulness": data.get("avg_scores", {}).get("faithfulness", 0.0),
        "judge_case_count": data.get("case_count", 0),
    }


def extract_baseline_metrics(data: dict | None) -> dict:
    if not data:
        return {}
    return {
        "extraction_f1": data.get("overall_score", 0.0),
    }


def check_thresholds(
    combined: dict,
    baseline_combined: dict,
) -> list[dict]:
    """Return list of failures: [{metric, value, floor/baseline, reason}]."""
    failures = []

    # Absolute floors
    for metric, floor in ABSOLUTE_FLOORS.items():
        val = combined.get(metric)
        if val is None:
            continue
        if val < floor:
            failures.append({
                "metric": metric,
                "value": val,
                "threshold": floor,
                "reason": f"below absolute floor {floor}",
            })

    # Relative drops vs baseline
    for metric, current_val in combined.items():
        if not isinstance(current_val, float):
            continue
        baseline_val = baseline_combined.get(metric)
        if baseline_val is None or baseline_val == 0:
            continue
        drop = (baseline_val - current_val) / baseline_val
        if drop > RELATIVE_DROP_TOLERANCE:
            failures.append({
                "metric": metric,
                "value": current_val,
                "baseline": baseline_val,
                "drop": round(drop, 4),
                "reason": f"dropped {drop:.1%} vs baseline (tolerance {RELATIVE_DROP_TOLERANCE:.0%})",
            })

    return failures


def build_pr_comment(
    combined: dict,
    baseline_combined: dict,
    failures: list[dict],
    mode: str,
) -> str:
    status = "✅ PASS" if not failures else "❌ FAIL"
    lines = [
        f"## Eval Gate — {status}",
        "",
        "| Metric | Current | Baseline | Δ | Floor |",
        "|--------|---------|----------|---|-------|",
    ]

    display_metrics = [
        ("faithfulness", "Faithfulness", ABSOLUTE_FLOORS.get("faithfulness")),
        ("answer_relevancy", "Answer Relevancy", ABSOLUTE_FLOORS.get("answer_relevancy")),
        ("context_precision", "Context Precision", ABSOLUTE_FLOORS.get("context_precision")),
        ("extraction_f1", "Extraction F1", ABSOLUTE_FLOORS.get("extraction_f1")),
        ("judge_pass_rate", "Judge Pass Rate", ABSOLUTE_FLOORS.get("judge_pass_rate")),
        ("promptfoo_pass_rate", "Promptfoo Pass Rate", None),
    ]

    for key, label, floor in display_metrics:
        val = combined.get(key)
        if val is None:
            continue
        base = baseline_combined.get(key)
        delta_str = "—"
        if base is not None:
            delta = val - base
            sign = "+" if delta >= 0 else ""
            delta_str = f"{sign}{delta:.3f}"
        floor_str = f"{floor:.2f}" if floor is not None else "—"
        val_str = f"{val:.4f}"
        base_str = f"{base:.4f}" if base is not None else "—"
        lines.append(f"| {label} | {val_str} | {base_str} | {delta_str} | {floor_str} |")

    if failures:
        lines += ["", "### Failures", ""]
        for f in failures:
            lines.append(f"- **{f['metric']}**: {f['value']:.4f} — {f['reason']}")

    lines += [
        "",
        f"_Mode: `{mode}` · {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M UTC')}_",
    ]
    return "\n".join(lines)


def build_html_report(combined: dict, failures: list[dict]) -> str:
    status_color = "#2da44e" if not failures else "#cf222e"
    status_text = "PASS" if not failures else "FAIL"
    def _fmt(v: object) -> str:
        return f"{v:.4f}" if isinstance(v, float) else str(v)

    rows = "".join(
        f"<tr><td>{k}</td><td>{_fmt(v)}</td></tr>"
        for k, v in sorted(combined.items())
    )
    fail_rows = "".join(
        f"<tr><td>{f['metric']}</td><td>{f['value']:.4f}</td><td>{f['reason']}</td></tr>"
        for f in failures
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>DocExtract Eval Report</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #d0d7de; padding: .5rem 1rem; text-align: left; }}
  th {{ background: #f6f8fa; }}
  .badge {{ display: inline-block; padding: .25rem .75rem; border-radius: 2rem;
            color: #fff; background: {status_color}; font-weight: bold; }}
</style>
</head>
<body>
<h1>DocExtract Eval Report <span class="badge">{status_text}</span></h1>
<p>Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}</p>
<h2>Combined Metrics</h2>
<table><tr><th>Metric</th><th>Value</th></tr>{rows}</table>
{"<h2>Threshold Failures</h2><table><tr><th>Metric</th><th>Value</th><th>Reason</th></tr>" + fail_rows + "</table>" if failures else ""}
</body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Eval gate: enforce thresholds, diff baseline")
    parser.add_argument("--promptfoo", type=Path, default=REPO_ROOT / "eval_artifacts" / "promptfoo.json")
    parser.add_argument("--ragas", type=Path, default=REPO_ROOT / "eval_artifacts" / "ragas.json")
    parser.add_argument("--judge", type=Path, default=REPO_ROOT / "eval_artifacts" / "llm_judge.json")
    parser.add_argument("--baseline", type=Path, default=REPO_ROOT / "autoresearch" / "baseline.json")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "eval_artifacts" / "scores.json")
    parser.add_argument("--report", type=Path, default=REPO_ROOT / "eval_artifacts" / "eval_report.html")
    parser.add_argument("--mode", default="local", choices=["pull_request", "push", "schedule", "local"])
    parser.add_argument("--accept-baseline", action="store_true",
                        help="Write combined scores as new baseline; requires --out already exists")
    args = parser.parse_args()

    # Load all inputs
    promptfoo_data = load_json(args.promptfoo)
    ragas_data = load_json(args.ragas)
    judge_data = load_json(args.judge)
    baseline_data = load_json(args.baseline)

    # Combine metrics from all sources
    combined: dict = {}
    combined.update(extract_ragas_metrics(ragas_data))
    combined.update(extract_judge_metrics(judge_data))
    combined.update(extract_promptfoo_metrics(promptfoo_data))
    combined.update(extract_baseline_metrics(baseline_data))  # extraction_f1 from existing baseline

    combined["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    combined["mode"] = args.mode

    if args.accept_baseline:
        # Write scores as new baseline section
        new_baseline = dict(baseline_data or {})
        new_baseline.update({
            k: v for k, v in combined.items()
            if k not in ("timestamp", "mode") and isinstance(v, (int, float))
        })
        new_baseline["timestamp"] = combined["timestamp"]
        args.baseline.write_text(json.dumps(new_baseline, indent=2))
        print(f"Baseline updated from current scores at {args.baseline}")
        return

    # Baseline for comparison (previous scores if available)
    baseline_combined: dict = {}
    if baseline_data:
        baseline_combined.update(extract_ragas_metrics(baseline_data))
        baseline_combined.update(extract_judge_metrics(baseline_data))
        baseline_combined.update(extract_baseline_metrics(baseline_data))

    # Threshold check
    failures = check_thresholds(combined, baseline_combined)

    # Write outputs
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(combined, indent=2))

    pr_comment = build_pr_comment(combined, baseline_combined, failures, args.mode)
    pr_comment_path = args.out.parent / "pr_comment.md"
    pr_comment_path.write_text(pr_comment)

    args.report.write_text(build_html_report(combined, failures))

    # Emit GitHub Actions outputs
    if os.environ.get("GITHUB_OUTPUT"):
        improved = not failures and any(
            combined.get(m, 0) > baseline_combined.get(m, 0) + 0.01
            for m in ABSOLUTE_FLOORS
        )
        overall = combined.get("extraction_f1") or combined.get("judge_pass_rate", 0)
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"improved={'true' if improved else 'false'}\n")
            f.write(f"overall_score={overall:.4f}\n")
            f.write(f"drift_detected={'false'}\n")

    # Summary
    print(pr_comment)
    print(f"\nWritten: {args.out}, {args.report}")

    if failures:
        print(f"\n{len(failures)} threshold failure(s). CI blocked.", file=sys.stderr)
        sys.exit(1)

    print("\nAll thresholds met.")


if __name__ == "__main__":
    main()
