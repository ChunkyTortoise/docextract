"""Tests for scripts/eval_braintrust.py pure logic (no Braintrust account needed)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "eval_braintrust", _REPO / "scripts" / "eval_braintrust.py"
)
eb = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(eb)


@pytest.fixture(scope="module")
def cases():
    return eb.load_cases()


def test_load_cases_returns_fixture_backed_cases(cases):
    # 28 committed golden_responses fixtures pair with the 72-case corpus.
    assert len(cases) == 28
    assert all("case" in c and "parsed" in c for c in cases)
    assert all(c["case"].get("id") for c in cases)


def test_build_dataset_row_shape(cases):
    rows = eb.build_dataset(cases)
    assert len(rows) == len(cases)
    row = rows[0]
    assert set(row) == {"input", "expected", "metadata"}
    assert "id" in row["input"] and "text" in row["input"]
    assert "critical_fields" in row["metadata"]


def test_field_f1_scorer_matches_offline_gate(cases):
    # Weighted field-F1 must reproduce the CI offline gate's combined number.
    crit_by_id = {c["case"]["id"]: c["case"].get("critical_fields", []) for c in cases}
    scorer = eb.make_field_f1(crit_by_id)
    parsed_by_id = {c["case"]["id"]: c["parsed"] for c in cases}
    rows = eb.build_dataset(cases)
    total_w = 0.0
    acc = 0.0
    for row in rows:
        cid = row["input"]["id"]
        s = scorer(row["input"], parsed_by_id[cid], row["expected"])
        assert 0.0 <= s <= 1.0
        w = row["metadata"]["weight"]
        total_w += w
        acc += s * w
    assert round(acc / total_w, 4) == 0.9555


def test_dry_run_returns_zero(cases):
    crit_by_id = {c["case"]["id"]: c["case"].get("critical_fields", []) for c in cases}
    assert eb.run_dry(cases, crit_by_id) == 0
