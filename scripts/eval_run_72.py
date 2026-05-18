"""Live 72-case eval driver. Reuses autoresearch.eval scoring + the real extractor.

Why this exists: autoresearch.eval.main() only prints an aggregate SCORE and does not
persist per-case parsed extractions, which we need for (a) golden/adversarial split F1
and (b) recording golden_responses fixtures for deterministic CI replay. This driver
makes the same live two-pass Claude calls, scores with the same score_extraction, and
emits both artifacts in one run. Scoring logic is imported, not reimplemented.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from autoresearch.eval import score_extraction

REPO = Path(__file__).resolve().parents[1]
DATASET = REPO / "autoresearch" / "eval_dataset_72.json"
FIXTURE_DIR = REPO / "autoresearch" / "golden_responses"
RUN_OUT = REPO / "autoresearch" / f"eval_run_72_{datetime.now().strftime('%Y%m%d')}.json"
CONCURRENCY = 5


async def run_case(case: dict, sem: asyncio.Semaphore) -> dict:
    from app.services.claude_extractor import extract

    async with sem:
        try:
            result = await extract(case["input_text"], case["doc_type"])
            extracted = result.data or {}
            model = getattr(result, "model_used", "") or ""
            raw = getattr(result, "raw_response", "") or ""
            err = None
        except Exception as e:  # record, do not abort the sweep
            extracted, model, raw, err = {}, "", "", f"{type(e).__name__}: {e}"

    score = score_extraction(extracted, case["expected"], case["critical_fields"])
    return {
        "id": case["id"],
        "split": case["split"],
        "doc_type": case["doc_type"],
        "weight": case["weight"],
        "score": score,
        "model": model,
        "extracted": extracted,
        "raw_response": raw,
        "error": err,
    }


def weighted(rows: list[dict]) -> float:
    tw = sum(r["weight"] for r in rows)
    return sum(r["score"] * r["weight"] for r in rows) / tw if tw else 0.0


async def main() -> None:
    dataset = json.loads(DATASET.read_text())
    sem = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(*(run_case(c, sem) for c in dataset))

    now = datetime.now(UTC).isoformat()
    for r in results:
        if r["error"]:
            continue
        (FIXTURE_DIR / f"{r['id']}.json").write_text(
            json.dumps(
                {
                    "case_id": r["id"],
                    "model": r["model"],
                    "recorded_at": now,
                    "raw_response": r["raw_response"],
                    "parsed_extraction": r["extracted"],
                },
                indent=2,
            )
        )

    golden = [r for r in results if r["split"] == "golden"]
    adv = [r for r in results if r["split"] == "adversarial"]
    per_doc: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        per_doc[r["doc_type"]].append(r)

    summary = {
        "timestamp": now,
        "dataset": str(DATASET.relative_to(REPO)),
        "case_count": len(results),
        "errors": [r["id"] for r in results if r["error"]],
        "extraction_f1_combined": round(weighted(results), 6),
        "extraction_f1_golden": round(weighted(golden), 6),
        "extraction_f1_adversarial": round(weighted(adv), 6),
        "n_golden": len(golden),
        "n_adversarial": len(adv),
        "per_doc_type": {
            dt: {"score": round(weighted(rs), 4), "count": len(rs)}
            for dt, rs in sorted(per_doc.items())
        },
        "per_case": [
            {k: r[k] for k in ("id", "split", "doc_type", "weight", "score", "error")}
            for r in sorted(results, key=lambda x: x["id"])
        ],
    }
    RUN_OUT.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "per_case"}, indent=2))
    print(f"\nwrote {RUN_OUT.relative_to(REPO)}")


if __name__ == "__main__":
    asyncio.run(main())
