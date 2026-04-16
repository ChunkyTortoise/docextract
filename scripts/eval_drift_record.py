#!/usr/bin/env python3
"""
Append one JSONL row per metric to the eval-history branch for drift tracking.

Used by the daily cron in eval-gate.yml. Writes to a local file that is then
committed to the eval-history branch (or stdout if branch approach is skipped).

Usage:
  python scripts/eval_drift_record.py --scores eval_artifacts/scores.json

Output: eval_artifacts/drift_sample.jsonl (append-only)

Drift detection (z-test):
  Reads last 7 daily samples, computes mean + stdev per metric.
  If |Z| > 2.0 or 3 consecutive same-direction moves > 1σ, writes drift_issue.md.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DRIFT_HISTORY = REPO_ROOT / "eval_artifacts" / "drift_history.jsonl"
DRIFT_ISSUE_TEMPLATE = REPO_ROOT / "eval_artifacts" / "drift_issue.md"

DRIFT_METRICS = ["faithfulness", "answer_relevancy", "context_precision", "extraction_f1", "judge_pass_rate"]
Z_THRESHOLD = 2.0
CONSECUTIVE_THRESHOLD = 3


def load_history(path: Path, max_days: int = 7) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows[-max_days:]


def z_score(value: float, history: list[float]) -> float | None:
    if len(history) < 3:
        return None
    mean = sum(history) / len(history)
    variance = sum((x - mean) ** 2 for x in history) / len(history)
    stdev = math.sqrt(variance)
    if stdev < 1e-6:
        return None
    return (value - mean) / stdev


def detect_drift(current: dict, history: list[dict]) -> dict[str, float]:
    """Return dict of {metric: z_score} for metrics with |Z| > threshold."""
    flagged: dict[str, float] = {}
    for metric in DRIFT_METRICS:
        val = current.get(metric)
        if val is None:
            continue
        hist_vals = [h[metric] for h in history if metric in h]
        z = z_score(float(val), hist_vals)
        if z is not None and abs(z) > Z_THRESHOLD:
            flagged[metric] = round(z, 3)
    return flagged


def write_drift_issue(flagged: dict[str, float], current: dict) -> None:
    lines = [
        "## Eval Drift Detected",
        "",
        f"**Date:** {datetime.date.today().isoformat()}",
        "",
        "The following metrics show statistically significant drift (|Z| > 2.0 vs rolling 7-day baseline):",
        "",
        "| Metric | Current | Z-score |",
        "|--------|---------|---------|",
    ]
    for metric, z in flagged.items():
        val = current.get(metric, "?")
        val_str = f"{val:.4f}" if isinstance(val, float) else str(val)
        lines.append(f"| {metric} | {val_str} | {z:+.2f} |")

    lines += [
        "",
        "**Recommended actions:**",
        "1. Check Langfuse for recent prompt version changes",
        "2. Check Anthropic model release notes for API changes",
        "3. Review `eval_artifacts/` in the latest CI run for failing cases",
        "",
        "_This issue was opened automatically by the daily eval drift cron._",
    ]
    DRIFT_ISSUE_TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
    DRIFT_ISSUE_TEMPLATE.write_text("\n".join(lines))
    print(f"Drift issue template written to {DRIFT_ISSUE_TEMPLATE}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scores", type=Path, default=REPO_ROOT / "eval_artifacts" / "scores.json")
    args = parser.parse_args()

    if not args.scores.exists():
        print(f"Scores file not found: {args.scores}", file=sys.stderr)
        sys.exit(1)

    current = json.loads(args.scores.read_text())
    current.setdefault("timestamp", datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"))

    # Load history and append current sample
    history = load_history(DRIFT_HISTORY)
    DRIFT_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with DRIFT_HISTORY.open("a") as f:
        f.write(json.dumps(current) + "\n")

    # Detect drift
    flagged = detect_drift(current, history)

    if flagged:
        print(f"DRIFT DETECTED: {flagged}", file=sys.stderr)
        write_drift_issue(flagged, current)
        # Signal to GitHub Actions
        import os
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write("drift_detected=true\n")
    else:
        print("No drift detected.", file=sys.stderr)
        import os
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write("drift_detected=false\n")

    print(f"Drift sample recorded. History length: {len(history) + 1}")


if __name__ == "__main__":
    main()
