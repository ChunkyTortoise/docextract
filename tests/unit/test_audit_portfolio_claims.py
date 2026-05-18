from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_portfolio_claims import count_jsonl_cases, scan_docs


def test_count_jsonl_cases_skips_meta_rows(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    rows = [
        {"_meta": {"version": "1.0.0"}},
        {"id": "invoice_01"},
        {"id": "receipt_01"},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    assert count_jsonl_cases(path) == 2


def test_scan_docs_allows_canonical_metrics(tmp_path: Path) -> None:
    doc = tmp_path / "README.md"
    doc.write_text(
        "95.5% F1 baseline, 72-case corpus, 51 golden cases, "
        "21 adversarial cases, 1,260 collected tests, 81.59% coverage."
    )

    assert scan_docs([doc]) == []


def test_scan_docs_flags_stale_metrics(tmp_path: Path) -> None:
    doc = tmp_path / "CASE_STUDY.md"
    doc.write_text("94.6% accuracy over 28 fixtures with 1,155 tests.")

    findings = scan_docs([doc])

    assert len(findings) == 2
    assert any("94.6%" in finding for finding in findings)
    assert any("1,155" in finding for finding in findings)
