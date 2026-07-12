"""Tests for scripts/check_metrics_ledger.py — metrics provenance checker.

TDD spec (Task 6):
  1. Markdown with a metric claim backed by a status=measured ledger row → exits 0
  2. Markdown with a metric claim backed by a status=modeled ledger row → exits nonzero
  3. Markdown with a metric claim with no matching ledger row → exits nonzero
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import yaml

SCRIPT = Path(__file__).parents[2] / "scripts" / "check_metrics_ledger.py"


def _write_ledger(tmp_path: Path, metrics: list[dict]) -> Path:
    ledger_path = tmp_path / "portfolio-metrics.yaml"
    ledger_path.write_text(yaml.dump({"schema_version": 2, "metrics": metrics}))
    return ledger_path


def _write_md(tmp_path: Path, content: str, name: str = "test.md") -> Path:
    md_path = tmp_path / name
    md_path.write_text(textwrap.dedent(content))
    return md_path


def _run(md_path: Path, ledger_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(md_path), "--ledger", str(ledger_path)],
        capture_output=True,
        text=True,
    )


# ──────────────────────────────────────────────
# Test 1: measured row backing a claim → pass
# ──────────────────────────────────────────────

def test_measured_row_backing_claim_passes(tmp_path):
    """A metric claim that has a matching status=measured ledger row exits 0."""
    ledger = _write_ledger(
        tmp_path,
        [
            {
                "id": "local_load_p95_ms",
                "value": "412ms",
                "status": "measured",
                "source_command": "locust ...",
                "artifact_path": "results/local-stub_stats.csv",
                "date": "2026-06-12",
                "context": "Apple M1, 20 users, 5m, extraction stubbed",
            }
        ],
    )
    md = _write_md(tmp_path, """\
        ## Performance

        Measured p95 latency of 412ms under a 20-user Locust run (extraction stubbed).
    """)

    result = _run(md, ledger)
    assert result.returncode == 0, f"Expected 0, got {result.returncode}. stderr={result.stderr}"


# ──────────────────────────────────────────────
# Test 2: modeled row backing a claim → fail
# ──────────────────────────────────────────────

def test_modeled_row_backing_claim_fails(tmp_path):
    """A metric claim that only has a status=modeled row exits nonzero."""
    ledger = _write_ledger(
        tmp_path,
        [
            {
                "id": "avg_cost_per_document_usd",
                "value": "$0.03/doc",
                "status": "modeled",
                "source_command": "",
                "artifact_path": "",
                "date": "2026-05-17",
                "context": "modeled from token pricing table",
            }
        ],
    )
    md = _write_md(tmp_path, """\
        ## Cost

        Average cost is $0.03/doc based on the pricing model.
    """)

    result = _run(md, ledger)
    assert result.returncode != 0, (
        f"Expected nonzero exit for modeled-only backing, got 0. stdout={result.stdout}"
    )


# ──────────────────────────────────────────────
# Test 3: no matching row → fail
# ──────────────────────────────────────────────

def test_no_matching_ledger_row_fails(tmp_path):
    """A metric claim with no ledger row at all exits nonzero."""
    ledger = _write_ledger(tmp_path, [])  # empty ledger
    md = _write_md(tmp_path, """\
        ## Performance

        The system achieves 250 QPS under load.
    """)

    result = _run(md, ledger)
    assert result.returncode != 0, (
        f"Expected nonzero exit for unclaimed metric, got 0. stdout={result.stdout}"
    )
