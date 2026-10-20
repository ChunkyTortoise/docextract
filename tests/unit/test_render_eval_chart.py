"""Tests for scripts/render_eval_chart.py: data-driven labels, sort order, derived axis,
CLI behavior, and freshness of the committed SVGs against the committed fixtures."""

from __future__ import annotations

import json
import runpy
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts import render_eval_chart as rec

SVG_NS = "{http://www.w3.org/2000/svg}"
COMMITTED_DIR = rec.REPO / "docs" / "assets" / "eval"
NAMES = ("replay-by-doc-type-light.svg", "replay-by-doc-type-dark.svg")

# Invented values, chosen so the minimum (0.62) forces a derived axis start of 0.55.
SYNTHETIC_TYPES = {
    "alpha_form": (0.7311, 5),
    "beta_sheet": (0.62, 2),
    "gamma_note": (0.9478, 9),
    "delta_card": (0.7311, 1),
}


def _synthetic(spelling: str) -> dict:
    combined_key, type_key = (
        ("extraction_f1_combined", "f1")
        if spelling == "legacy"
        else ("field_acc_combined", "field_acc")
    )
    return {
        "corpus_cases": 40,
        "replayed": 17,
        "pending_fixtures": 23,
        combined_key: 0.8012,
        "floor": 0.7,
        "per_doc_type": {
            name: {type_key: score, "count": count}
            for name, (score, count) in SYNTHETIC_TYPES.items()
        },
    }


def _texts(svg_path: Path) -> list[str]:
    root = ET.parse(svg_path).getroot()
    return [el.text or "" for el in root.iter() if el.tag in {f"{SVG_NS}text", f"{SVG_NS}title", f"{SVG_NS}desc"}]


def _row_labels(svg_path: Path) -> list[str]:
    root = ET.parse(svg_path).getroot()
    return [
        el.text or ""
        for el in root.iter(f"{SVG_NS}text")
        if el.get("font-size") == "13" and el.get("text-anchor") is None
    ]


@pytest.mark.parametrize("spelling", ["legacy", "renamed"])
def test_synthetic_replay_renders_data_driven_chart(tmp_path: Path, spelling: str) -> None:
    src = tmp_path / "replay.json"
    src.write_text(json.dumps(_synthetic(spelling)))
    assert rec.main(["--in", str(src), "--out-dir", str(tmp_path)]) == 0

    for name in NAMES:
        texts = _texts(tmp_path / name)
        joined = "\n".join(texts)
        for score, count in SYNTHETIC_TYPES.values():
            assert f"{score:.4f}" in texts
            assert f"(n={count})" in joined
        assert "0.8012" in texts
        assert "all fixtures (n=17)" in texts
        assert "CI floor 0.7" in texts
        assert "17 committed fixtures, 23 of 40 lookup cases pending." in joined
        assert "axis starts at 0.55" in joined
        assert "0.55" in texts and "1.00" in texts and "0.50" not in texts
        assert "F1" not in joined
        assert chr(0x2013) not in joined and chr(0x2014) not in joined

        labels = _row_labels(tmp_path / name)
        assert labels[0] == "all fixtures (n=17)"
        assert labels[1:] == [
            "gamma_note (n=9)",
            "alpha_form (n=5)",
            "delta_card (n=1)",
            "beta_sheet (n=2)",
        ]


def test_axis_lo_is_derived_from_data_and_floor() -> None:
    data = rec.parse_replay(_synthetic("legacy"))
    assert rec.axis_lo(data) == 0.55

    high = _synthetic("legacy")
    high["per_doc_type"] = {"only": {"f1": 0.97, "count": 3}}
    high["extraction_f1_combined"] = 0.97
    high["floor"] = 0.9
    assert rec.axis_lo(rec.parse_replay(high)) == 0.85


def test_rendering_is_byte_deterministic() -> None:
    summary = _synthetic("renamed")
    assert rec.render_all(summary) == rec.render_all(json.loads(json.dumps(summary)))
    for text in rec.render_all(summary).values():
        assert text.endswith("</svg>\n")
        assert "\r" not in text


def test_committed_charts_match_live_replay(tmp_path: Path) -> None:
    """Freshness: running the real replay and rendering reproduces the committed SVGs."""
    assert rec.main(["--out-dir", str(tmp_path)]) == 0
    for name in NAMES:
        assert (tmp_path / name).read_bytes() == (COMMITTED_DIR / name).read_bytes(), name


def test_check_flag_detects_drift(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "replay.json"
    src.write_text(json.dumps(_synthetic("legacy")))
    out = tmp_path / "out"

    assert rec.main(["--in", str(src), "--out-dir", str(out), "--check"]) == 1  # missing files
    assert rec.main(["--in", str(src), "--out-dir", str(out)]) == 0
    for name in NAMES:
        assert (out / name).is_file()
    assert rec.main(["--in", str(src), "--out-dir", str(out), "--check"]) == 0

    target = out / NAMES[1]
    raw = bytearray(target.read_bytes())
    raw[-2] = ord("X")
    target.write_bytes(bytes(raw))
    assert rec.main(["--in", str(src), "--out-dir", str(out), "--check"]) == 1
    assert NAMES[1] in capsys.readouterr().out


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.pop("floor"), "'floor'"),
        (lambda d: d.pop("replayed"), "'replayed'"),
        (lambda d: d.pop("extraction_f1_combined"), "field_acc_combined"),
        (lambda d: d["per_doc_type"]["alpha_form"].pop("count"), "per_doc_type['alpha_form']"),
        (lambda d: d["per_doc_type"]["beta_sheet"].pop("f1"), "per_doc_type['beta_sheet']"),
        (lambda d: d.update(per_doc_type={}), "per_doc_type"),
    ],
)
def test_missing_keys_raise_clear_error(mutate, message: str) -> None:
    summary = _synthetic("legacy")
    mutate(summary)
    with pytest.raises(rec.ReplayFormatError, match=message.replace("[", r"\[").replace("]", r"\]")):
        rec.render_all(summary)


def test_script_entry_point_check_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["render_eval_chart.py", "--check"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(rec.REPO / "scripts" / "render_eval_chart.py"), run_name="__main__")
    assert exc.value.code == 0
