"""The offline replay scorer drives the public Eval Gate badge — it must stay green
and deterministic with zero network. These tests lock that contract."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "eval_offline_replay.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )


def test_offline_replay_passes_deterministically() -> None:
    """Default invocation passes and reproduces the ~0.955 baseline F1, no API key."""
    r = _run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    summary = json.loads((REPO / "eval_artifacts" / "offline_replay.json").read_text())
    assert summary["replayed"] >= 28
    assert 0.90 <= summary["extraction_f1_combined"] <= 1.0
    assert summary["extraction_f1_combined"] >= summary["floor"]


def test_offline_replay_fails_below_floor() -> None:
    """An impossibly high floor must fail closed (regression guard works)."""
    r = _run("--floor", "0.999")
    assert r.returncode == 1
    assert "FAIL" in r.stdout


def test_offline_replay_fails_if_corpus_shrinks() -> None:
    """Requiring more fixtures than exist must fail (corpus cannot silently shrink)."""
    r = _run("--min-cases", "9999")
    assert r.returncode == 1
    assert "FAIL" in r.stdout
