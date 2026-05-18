"""Deterministic offline eval: score committed golden_responses fixtures, no API key.

This is the CI badge driver. Live LLM eval (Ragas + LLM-judge) needs a paid API key
that isn't available on scheduled/push runs, so it cannot gate the public badge. This
script replays the committed `autoresearch/golden_responses/<id>.json` fixtures (real
recorded extractor outputs) against the ground-truth corpus using the SAME weighted
scorer as the baseline — fully deterministic, zero network.

Coverage note: the corpus is `eval_dataset_72.json` (72 cases). Fixtures are recorded
by `scripts/benchmark.py` (a live run). Cases without a committed fixture are reported
as "pending" and skipped — NOT failed — so the badge stays honest while the remaining
fixtures are recorded as API budget allows. The replayed subset is still gated on a
hard floor and a regression check vs `autoresearch/baseline.json`.

Fails (exit 1) if:
  - fewer than --min-cases fixtures are present (the committed corpus must not shrink)
  - replayed combined weighted F1 falls below --floor
  - replayed combined F1 regresses more than --tolerance below baseline.json

Run:  .venv/bin/python scripts/eval_offline_replay.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from autoresearch.eval import score_extraction  # noqa: E402

DATASET = REPO / "autoresearch" / "eval_dataset_72.json"
FIXTURE_DIR = REPO / "autoresearch" / "golden_responses"
BASELINE = REPO / "autoresearch" / "baseline.json"


def _weighted(rows: list[dict]) -> float:
    tw = sum(r["weight"] for r in rows)
    return sum(r["score"] * r["weight"] for r in rows) / tw if tw else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--floor", type=float, default=0.85, help="hard minimum combined weighted F1")
    ap.add_argument("--tolerance", type=float, default=0.03, help="max F1 drop vs baseline.json")
    ap.add_argument("--min-cases", type=int, default=28, help="min fixtures required (corpus must not shrink)")
    ap.add_argument("--out", default="eval_artifacts/offline_replay.json")
    args = ap.parse_args()

    dataset = json.loads(DATASET.read_text())
    rows: list[dict] = []
    pending: list[str] = []
    for case in dataset:
        fx = FIXTURE_DIR / f"{case['id']}.json"
        if not fx.exists():
            pending.append(case["id"])
            continue
        parsed = json.loads(fx.read_text()).get("parsed_extraction", {}) or {}
        rows.append(
            {
                "id": case["id"],
                "split": case["split"],
                "doc_type": case["doc_type"],
                "weight": case["weight"],
                "score": score_extraction(parsed, case["expected"], case["critical_fields"]),
            }
        )

    golden = [r for r in rows if r["split"] == "golden"]
    adv = [r for r in rows if r["split"] == "adversarial"]
    per_doc: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        per_doc[r["doc_type"]].append(r)

    combined = round(_weighted(rows), 4)
    baseline_score = json.loads(BASELINE.read_text()).get("overall_score") if BASELINE.exists() else None

    summary = {
        "corpus_cases": len(dataset),
        "replayed": len(rows),
        "pending_fixtures": len(pending),
        "pending_ids_sample": sorted(pending)[:8],
        "extraction_f1_combined": combined,
        "extraction_f1_golden": round(_weighted(golden), 4),
        "extraction_f1_adversarial": round(_weighted(adv), 4),
        "baseline_score": baseline_score,
        "floor": args.floor,
        "per_doc_type": {
            dt: {"f1": round(_weighted(rs), 4), "count": len(rs)} for dt, rs in sorted(per_doc.items())
        },
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))

    if len(rows) < args.min_cases:
        print(f"\nFAIL: only {len(rows)} fixtures present; corpus must keep >= {args.min_cases}")
        return 1
    if combined < args.floor:
        print(f"\nFAIL: combined F1 {combined} < floor {args.floor}")
        return 1
    if baseline_score is not None and combined < baseline_score - args.tolerance:
        print(f"\nFAIL: combined F1 {combined} regressed > {args.tolerance} below baseline {baseline_score}")
        return 1

    print(
        f"\nPASS: replayed {len(rows)}/{len(dataset)} corpus cases — combined F1 {combined} "
        f"(baseline {baseline_score}, floor {args.floor}); {len(pending)} fixtures pending live recording"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
