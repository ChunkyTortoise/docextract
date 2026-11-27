"""The Space replay page must report the same numbers as the CI eval scripts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import space_app

REPO = Path(__file__).resolve().parents[2]


def test_replay_matches_offline_replay_script(tmp_path):
    out = tmp_path / "replay.json"
    subprocess.run(
        [sys.executable, "scripts/eval_offline_replay.py", "--out", str(out)],
        cwd=REPO,
        check=True,
        capture_output=True,
    )
    script = json.loads(out.read_text())
    page = space_app.replay()
    assert page["combined"] == script["field_acc_combined"]
    assert len(page["rows"]) == script["replayed"]
    assert page["pending"] == script["pending_fixtures"]
    for doc_type, summary in script["per_doc_type"].items():
        assert page["per_doc_type"][doc_type] == (summary["field_acc"], summary["count"])


def test_grounding_matches_hallucination_scorer():
    from autoresearch.grounding import score_grounding

    dataset = {c["id"]: c for c in json.loads(space_app.DATASET.read_text())}
    claims = unsupported = 0
    for fixture in sorted(space_app.FIXTURE_DIR.glob("*.json")):
        case = dataset[fixture.stem]
        parsed = json.loads(fixture.read_text()).get("parsed_extraction", {}) or {}
        result = score_grounding(parsed, case["input_text"])
        claims += len(result.scored)
        unsupported += len(result.unsupported)
    page = space_app.replay()
    assert (page["claims"], page["unsupported"]) == (claims, unsupported)


def test_page_renders_without_exceptions():
    apptest = pytest.importorskip("streamlit.testing.v1")
    at = apptest.AppTest.from_file(str(REPO / "space_app.py"), default_timeout=60).run()
    assert not at.exception
    assert at.selectbox[0].options
