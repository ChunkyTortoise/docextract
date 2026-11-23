"""The committed injection scan results must match what the scan produces today."""

from __future__ import annotations

from app.services import injection_guard
from scripts import eval_injection_scan as scan_eval


def test_committed_doc_matches_current_scan():
    result = scan_eval.score(scan_eval.load_cases())
    assert scan_eval.DOC_PATH.read_text() == scan_eval.render_doc(result)


def test_counts_are_consistent_with_the_corpus():
    cases = scan_eval.load_cases()
    result = scan_eval.score(cases)
    attacks = [c for c in cases if c.get("attack_type") == scan_eval.INJECTION_TYPE]
    assert result["attack_cases"] == len(attacks)
    assert result["attack_cases"] + result["benign_cases"] == len(cases)
    assert result["attacks_detected"] + len(result["missed"]) == result["attack_cases"]
    # Each verdict agrees with calling the guard directly.
    by_id = {c["id"]: c for c in cases}
    for attack in result["attacks"]:
        assert attack["hits"] == injection_guard.scan(by_id[attack["id"]]["input_text"])


def test_check_mode_detects_a_stale_doc(tmp_path, monkeypatch, capsys):
    stale = tmp_path / "injection-scan-results.md"
    stale.write_text("# old\n")
    monkeypatch.setattr(scan_eval, "DOC_PATH", stale)
    assert scan_eval.main(["--check"]) == 1
    assert "STALE" in capsys.readouterr().out
