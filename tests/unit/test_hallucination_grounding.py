"""Unit tests for the deterministic hallucination scorer (autoresearch/grounding.py)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from autoresearch.grounding import score_grounding

REPO = Path(__file__).resolve().parents[2]

INVOICE = """INVOICE
Invoice Number: INV-2024-001
Date: January 15, 2024
From: Acme Corp
Subtotal: $1,000.00
Total Due: $1,080.00
Currency: USD
"""


def _unsupported_paths(extraction: dict, source: str) -> set[str]:
    return {c.path for c in score_grounding(extraction, source).unsupported}


def test_grounded_extraction_scores_one() -> None:
    r = score_grounding(
        {
            "invoice_number": "INV-2024-001",
            "invoice_date": "2024-01-15",
            "vendor_name": "acme corp",
            "total_amount": 1080.0,
        },
        INVOICE,
    )
    assert r.faithfulness == 1.0
    assert r.hallucination_rate == 0.0


def test_invented_vendor_and_wrong_total_are_flagged() -> None:
    bad = {"invoice_number": "INV-2024-001", "vendor_name": "Ghost LLC", "total_amount": 1180.0}
    assert _unsupported_paths(bad, INVOICE) == {"vendor_name", "total_amount"}
    assert score_grounding(bad, INVOICE).faithfulness == pytest.approx(1 / 3)


def test_wrong_date_is_flagged() -> None:
    assert _unsupported_paths({"invoice_date": "2024-01-16"}, INVOICE) == {"invoice_date"}


def test_nulls_and_normalized_labels_are_not_scored() -> None:
    r = score_grounding({"customer_name": None, "currency": "EUR", "notes": ""}, INVOICE)
    assert r.scored == []
    assert r.faithfulness == 1.0


def test_eu_number_format() -> None:
    src = "Gesamtbetrag / Total: 1.487,50 EUR\nMwSt: 237,50 EUR"
    assert _unsupported_paths({"total_amount": 1487.5, "tax_amount": 237.5}, src) == set()


def test_ocr_lookalikes_count_as_grounded_but_invention_does_not() -> None:
    src = "Frorn: Acrne lnc\nT0tal: $1,65O.OO"
    r = score_grounding({"vendor_name": "Acme Inc", "total_amount": 1650.0}, src)
    assert r.faithfulness == 1.0
    assert {c.match for c in r.claims} == {"ocr"}
    assert _unsupported_paths({"vendor_name": "Acme Ltd", "total_amount": 1600.0}, src) == {
        "vendor_name",
        "total_amount",
    }


def test_name_composed_from_separate_lines() -> None:
    src = "Surname: RODRIGUEZ\nGiven Names: MARIA ELENA"
    assert _unsupported_paths({"full_name": "RODRIGUEZ MARIA ELENA"}, src) == set()
    # Token matching is for names only: a merged description is still flagged.
    assert _unsupported_paths({"description": "ELENA MARIA RODRIGUEZ"}, src) == {"description"}


def test_brand_swapped_for_generic_drug_name_is_flagged() -> None:
    src = "Medications:\n2. Ozempic 0.5mg - Once weekly injection"
    assert _unsupported_paths(
        {"medications": [{"name": "Semaglutide", "dosage": "0.5mg"}]}, src
    ) == {"medications[0].name"}


def test_replay_script_passes_and_catches_planted_hallucinations(tmp_path: Path) -> None:
    out = tmp_path / "hallucination.json"
    proc = subprocess.run(
        [sys.executable, "scripts/eval_hallucination.py", "--out", str(out)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = json.loads(out.read_text())
    assert summary["cases"] >= 28
    assert summary["self_test"]["planted"] > 0
    assert summary["self_test"]["caught"] == summary["self_test"]["planted"]
