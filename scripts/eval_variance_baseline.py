#!/usr/bin/env python3
"""
Compute variance-calibrated relative-drop tolerance for the eval gate.

Runs (or ingests) N score snapshots at fixed config, records per-run
aggregate means, and derives:

    tolerance = max(2 * stdev, FLOOR)

where FLOOR defaults to 0.005 (0.5 percentage points on a 0–1 score).

Usage:
  # From existing score JSONs (offline / CI-friendly):
  python scripts/eval_variance_baseline.py \
    --scores-glob 'eval_artifacts/variance_runs/run_*.json' \
    --out eval_artifacts/variance_baseline.json

  # Or pass files explicitly:
  python scripts/eval_variance_baseline.py run1.json run2.json ... --out ...

Does not call paid APIs itself — feed it outputs from `make eval`.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

METRICS = [
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "extraction_f1",
    "judge_pass_rate",
]
DEFAULT_FLOOR = 0.005  # 0.5pt on a 0–1 score
DEFAULT_STDEV_MULT = 2.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((x - m) ** 2 for x in values) / len(values))


def extract_metric_series(runs: list[dict], metric: str) -> list[float]:
    series: list[float] = []
    for run in runs:
        val = run.get(metric)
        if isinstance(val, int | float):
            series.append(float(val))
    return series


def compute_tolerance(
    runs: list[dict],
    *,
    floor: float = DEFAULT_FLOOR,
    stdev_mult: float = DEFAULT_STDEV_MULT,
    metrics: list[str] | None = None,
) -> dict:
    """Return variance baseline payload with per-metric stats and gate tolerance.

    Overall relative-drop tolerance is the max of per-metric calibrated
    tolerances so the gate remains conservative across all tracked metrics.
    """
    metrics = metrics or METRICS
    per_metric: dict[str, dict] = {}
    calibrated: list[float] = []

    for metric in metrics:
        series = extract_metric_series(runs, metric)
        if len(series) < 2:
            continue
        stdev = _stdev(series)
        tol = max(stdev_mult * stdev, floor)
        per_metric[metric] = {
            "n": len(series),
            "mean": round(_mean(series), 6),
            "stdev": round(stdev, 6),
            "tolerance": round(tol, 6),
            "values": [round(v, 6) for v in series],
        }
        calibrated.append(tol)

    if not calibrated:
        raise ValueError(
            "Need at least 2 numeric samples for one of "
            f"{metrics} to compute variance tolerance"
        )

    overall = max(calibrated)
    return {
        "version": "1.0.0",
        "method": f"max({stdev_mult}*stdev, {floor})",
        "floor": floor,
        "stdev_mult": stdev_mult,
        "n_runs": len(runs),
        "relative_drop_tolerance": round(overall, 6),
        "per_metric": per_metric,
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
    }


def load_score_files(paths: list[Path]) -> list[dict]:
    runs: list[dict] = []
    for path in paths:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a JSON object of scores")
        runs.append(data)
    return runs


def resolve_score_paths(explicit: list[str], glob_pat: str | None) -> list[Path]:
    paths = [Path(p) for p in explicit]
    if glob_pat:
        paths.extend(sorted(REPO_ROOT.glob(glob_pat)))
    # de-dupe while preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in paths:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(p)
    return unique


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scores", nargs="*", help="Score JSON files from make eval")
    parser.add_argument(
        "--scores-glob",
        default=None,
        help="Glob relative to repo root (e.g. eval_artifacts/variance_runs/run_*.json)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "eval_artifacts" / "variance_baseline.json",
    )
    parser.add_argument("--floor", type=float, default=DEFAULT_FLOOR)
    parser.add_argument("--stdev-mult", type=float, default=DEFAULT_STDEV_MULT)
    args = parser.parse_args(argv)

    paths = resolve_score_paths(args.scores, args.scores_glob)
    if len(paths) < 2:
        print(
            "ERROR: need at least 2 score JSON files "
            "(pass paths or --scores-glob).",
            file=sys.stderr,
        )
        return 2

    runs = load_score_files(paths)
    payload = compute_tolerance(
        runs, floor=args.floor, stdev_mult=args.stdev_mult
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"Wrote {args.out}  relative_drop_tolerance="
        f"{payload['relative_drop_tolerance']:.4f}  n_runs={payload['n_runs']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
