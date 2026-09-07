"""Tests for the held-out vs simpler-baseline harness scaffold (CONT-RA10).

Dry-run / scaffold must exit 0 with no API calls and no invented scores.
Live without key or credit confirmation must refuse.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.held_out_baseline_benchmark import (
    STATUS,
    comparison_table_schema,
    critical_field_failures,
    main,
    score_extraction,
)

REPO = Path(__file__).resolve().parents[2]


def test_dry_run_prints_unmeasured_schema_and_exits_zero(capsys):
    rc = main(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert STATUS in out
    assert "UNMEASURED" in out
    assert "Field accuracy (overall, weighted)" in out
    assert "Critical-field failure rate" in out
    assert "simple (pass-1 only)" in out
    assert "full (two-pass)" in out
    assert "score_extraction" in out
    assert "Repeating offline replay does NOT satisfy this benchmark." in out
    assert "no API calls" in out


def test_scaffold_only_is_dry_run_alias(capsys):
    rc = main(["--scaffold-only"])
    out = capsys.readouterr().out
    assert rc == 0
    assert STATUS in out
    assert "UNMEASURED" in out


def test_default_invocation_is_scaffold_not_live(capsys):
    rc = main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "UNMEASURED" in out


def test_live_without_key_refuses(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = main(["--live", "--confirm-credit-spend"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "Refusing live API calls" in err
    assert "ANTHROPIC_API_KEY" in err


def test_live_without_credit_flag_refuses_even_with_key(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    rc = main(["--live"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "credit" in err.lower()
    assert "metering-runbook" in err


def test_live_with_empty_dataset_refuses(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    rc = main(["--live", "--confirm-credit-spend"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "Refusing live API calls" in err
    assert "empty" in err.lower() or "test_sha256" in err


def test_live_does_not_call_extract_when_refusing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    with patch("app.services.claude_extractor.extract") as mocked:
        rc = main(["--live", "--confirm-credit-spend"])
        assert rc == 2
        mocked.assert_not_called()


def test_comparison_table_schema_has_no_numeric_scores():
    table = comparison_table_schema()
    assert table.count("UNMEASURED") >= 7
    assert "95.5" not in table
    assert "%" not in table


def test_critical_field_failures_uses_score_extraction():
    expected = {"invoice_number": "INV-1", "total_amount": 10.0, "notes": "x"}
    extracted = {"invoice_number": "INV-1", "total_amount": None, "notes": "x"}
    failed, total = critical_field_failures(extracted, expected, ["invoice_number", "total_amount"])
    assert total == 2
    assert failed == 1
    # Same scorer the CI gate uses.
    assert score_extraction(extracted, expected, ["invoice_number", "total_amount"]) < 1.0


def test_stub_dataset_is_empty_array_not_fake_scores():
    payload = json.loads((REPO / "evals" / "held_out_live" / "test.json").read_text())
    assert payload == []
    manifest = json.loads(
        (REPO / "evals" / "held_out_live" / "partition_manifest.json").read_text()
    )
    assert manifest["test_sha256"] is None
    assert manifest["test_case_count"] is None
    assert STATUS in manifest["status"]


def test_benchmark_doc_status_banner():
    text = (REPO / "docs" / "held-out-baseline-benchmark.md").read_text()
    assert f"STATUS: {STATUS}" in text
    assert "PERFORMANCE UNMEASURED" in text
    assert "Do not invent" in text or "Do not cite this file as a measured result" in text
