"""Populate the docextract Langfuse dashboard by replaying recorded extractions.

Pairs eval_dataset_72.json cases with the committed golden_responses/<id>.json
fixtures (real recorded extractor outputs) and logs each as a Langfuse trace +
generation through the same langfuse_* helpers that trace_llm_call uses. No LLM
call, no cost, deterministic. Only the curated synthetic corpus is sent; inputs
and outputs are masked by sanitize_for_trace inside the helpers.

Requires LANGFUSE_ENABLED=true + keys in .env (loaded by pydantic-settings).

Usage:
    python scripts/langfuse_demo.py            # 6 cases
    python scripts/langfuse_demo.py --limit 12
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DATASET = REPO / "autoresearch" / "eval_dataset_72.json"
FIXTURE_DIR = REPO / "autoresearch" / "golden_responses"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=6, help="number of fixtures to replay")
    args = ap.parse_args()

    from app.observability import (
        get_langfuse,
        langfuse_end,
        langfuse_flush,
        langfuse_generation,
        langfuse_trace,
        setup_langfuse,
    )

    setup_langfuse()
    if get_langfuse() is None:
        print(
            "Langfuse client not initialized. Set LANGFUSE_ENABLED=true and keys in .env.",
            file=sys.stderr,
        )
        return 2

    dataset = json.loads(DATASET.read_text())
    emitted = 0
    for case in dataset:
        if emitted >= args.limit:
            break
        fx = FIXTURE_DIR / f"{case['id']}.json"
        if not fx.exists():
            continue
        rec = json.loads(fx.read_text())
        parsed = rec.get("parsed_extraction", {}) or {}
        model = rec.get("model", "claude-sonnet-4-6")

        trace = langfuse_trace(
            "extract",
            session_id=case["id"],
            metadata={"id": case["id"], "doc_type": case["doc_type"], "source": "golden_replay"},
            input=case["input_text"],
        )
        try:
            langfuse_generation(
                trace,
                "extract",
                model=model,
                input=case["input_text"],
                output=parsed,
                metadata={"doc_type": case["doc_type"], "split": case.get("split")},
            )
        finally:
            langfuse_end(trace)
        print(f"  emitted {case['id']:24s} doc_type={case['doc_type']}")
        emitted += 1

    langfuse_flush()
    print(json.dumps({"emitted": emitted}, indent=2))
    return 0 if emitted else 1


if __name__ == "__main__":
    raise SystemExit(main())
