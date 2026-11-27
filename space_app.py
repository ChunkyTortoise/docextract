"""Replay demo for a Hugging Face Space (or local Streamlit): no API key, no model calls.

It recomputes the two offline eval results from committed files in this repository:

- weighted field-level score of the 28 frozen prediction fixtures in
  autoresearch/golden_responses/ against autoresearch/eval_dataset_72.json,
  using the same scorer as scripts/eval_offline_replay.py;
- grounding of every extracted value in the source text, using the same scorer
  as scripts/eval_hallucination.py.

Run locally:  streamlit run space_app.py
Deploy steps: docs/deploy-hf-space.md
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from autoresearch.eval import score_extraction  # noqa: E402
from autoresearch.grounding import score_grounding  # noqa: E402

DATASET = REPO / "autoresearch" / "eval_dataset_72.json"
FIXTURE_DIR = REPO / "autoresearch" / "golden_responses"
BASELINE = REPO / "autoresearch" / "baseline.json"
FLOOR = 0.85


def _weighted(rows: list[dict]) -> float:
    total_weight = sum(r["weight"] for r in rows)
    return sum(r["score"] * r["weight"] for r in rows) / total_weight if total_weight else 0.0


def replay() -> dict:
    """Score every committed fixture. Pure function of files on disk."""
    dataset = json.loads(DATASET.read_text())
    rows: list[dict] = []
    pending: list[str] = []
    for case in dataset:
        fixture_path = FIXTURE_DIR / f"{case['id']}.json"
        if not fixture_path.exists():
            pending.append(case["id"])
            continue
        fixture = json.loads(fixture_path.read_text())
        parsed = fixture.get("parsed_extraction", {}) or {}
        grounding = score_grounding(parsed, case["input_text"])
        rows.append(
            {
                "id": case["id"],
                "split": case["split"],
                "doc_type": case["doc_type"],
                "weight": case["weight"],
                "model": fixture.get("model"),
                "score": score_extraction(parsed, case["expected"], case["critical_fields"]),
                "claims": len(grounding.scored),
                "unsupported": [(c.path, c.value) for c in grounding.unsupported],
                "parsed": parsed,
                "expected": case["expected"],
                "input_text": case["input_text"],
            }
        )

    per_doc: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        per_doc[r["doc_type"]].append(r)
    claims = sum(r["claims"] for r in rows)
    unsupported = sum(len(r["unsupported"]) for r in rows)
    baseline = json.loads(BASELINE.read_text()).get("overall_score") if BASELINE.exists() else None
    return {
        "rows": rows,
        "corpus_cases": len(dataset),
        "pending": len(pending),
        "combined": round(_weighted(rows), 4),
        "baseline": baseline,
        "claims": claims,
        "unsupported": unsupported,
        "faithfulness": round((claims - unsupported) / claims, 4) if claims else 1.0,
        "per_doc_type": {
            dt: (round(_weighted(rs), 4), len(rs)) for dt, rs in sorted(per_doc.items())
        },
    }


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="DocExtract replay", layout="wide")
    result = replay()

    st.title("DocExtract: offline eval replay")
    st.write(
        "This page re-scores frozen extraction outputs that are committed to the repository. "
        "It calls no model and needs no API key. Scores reflect the recorded predictions, "
        "not live model performance."
    )

    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Weighted field-level score",
        f"{result['combined']:.4f}",
        help=f"{len(result['rows'])} of {result['corpus_cases']} cases have a fixture; CI floor {FLOOR}",
    )
    c2.metric("Baseline (baseline.json)", f"{result['baseline']}")
    c3.metric(
        "Values grounded in source",
        f"{result['claims'] - result['unsupported']}/{result['claims']}",
        help=f"faithfulness {result['faithfulness']}",
    )

    st.subheader("Score by document type")
    st.table(
        [
            {"document type": dt, "score": score, "fixtures": n}
            for dt, (score, n) in result["per_doc_type"].items()
        ]
    )

    st.subheader("Inspect one fixture")
    ids = [r["id"] for r in result["rows"]]
    chosen = st.selectbox("Fixture", ids)
    row = next(r for r in result["rows"] if r["id"] == chosen)
    st.write(
        f"Type `{row['doc_type']}`, split `{row['split']}`, weight {row['weight']}, "
        f"recorded model `{row['model']}`, field score {row['score']:.4f}, "
        f"{len(row['unsupported'])} unsupported of {row['claims']} scored values."
    )
    if row["unsupported"]:
        st.warning("Values not found in the source text:")
        st.table([{"field": p, "value": str(v)} for p, v in row["unsupported"]])
    left, mid, right = st.columns(3)
    with left:
        st.caption("Source text")
        st.code(row["input_text"], language=None)
    with mid:
        st.caption("Frozen prediction")
        st.json(row["parsed"])
    with right:
        st.caption("Expected")
        st.json(row["expected"])


if __name__ == "__main__":
    main()
