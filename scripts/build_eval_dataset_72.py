"""One-shot bridge: JSONL corpus (51 golden + 21 adversarial) -> legacy eval_dataset schema.

Produces autoresearch/eval_dataset_72.json so autoresearch.eval can score the full
72-case corpus with the same weighted field-level F1 used for the 28-case baseline.

The `expected_output` labels are human-authored ground truth (see docs/eval-methodology.md);
this script only re-keys/parses, it does not synthesize labels. A `split` field is added
so downstream reporting can separate golden vs adversarial F1 (legacy runner ignores it).
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "evals" / "golden_set.jsonl"
ADV = REPO / "evals" / "adversarial_set.jsonl"
OUT = REPO / "autoresearch" / "eval_dataset_72.json"


def parse_tags(tags: list[str]) -> tuple[float, list[str]]:
    weight = 1.0
    critical: list[str] = []
    for t in tags:
        if t.startswith("weight_"):
            weight = float(t.split("_", 1)[1])
        elif t.startswith("critical:"):
            critical = [c for c in t.split(":", 1)[1].split(",") if c]
    return weight, critical


def load(path: Path, split: str) -> list[dict]:
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if "_meta" in obj:
            continue
        weight, critical = parse_tags(obj.get("tags", []))
        out.append(
            {
                "id": obj["id"],
                "doc_type": obj["doc_type"],
                "weight": weight,
                "critical_fields": critical,
                "input_text": obj["input_text"],
                "expected": obj["expected_output"],
                "split": split,
            }
        )
    return out


def main() -> None:
    golden = load(GOLDEN, "golden")
    adv = load(ADV, "adversarial")
    dataset = golden + adv
    OUT.write_text(json.dumps(dataset, indent=2))
    ids = [c["id"] for c in dataset]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    print(f"golden={len(golden)} adversarial={len(adv)} total={len(dataset)} -> {OUT}")


if __name__ == "__main__":
    main()
