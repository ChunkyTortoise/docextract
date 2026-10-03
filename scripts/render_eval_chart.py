#!/usr/bin/env python3
"""Render the offline replay results as a per-document-type dot chart (SVG).

The chart is drawn from the JSON written by ``scripts/eval_offline_replay.py``,
so the committed images always trace back to the committed fixtures. Standard
library only; output is byte-deterministic (fixed float formatting, sorted rows,
no timestamps, LF line endings).

Usage:
  python scripts/render_eval_chart.py                 # run the replay, then render
  python scripts/render_eval_chart.py --in replay.json
  python scripts/render_eval_chart.py --check         # exit 1 if committed SVGs drift

Outputs (default ``docs/assets/eval/``):
  replay-by-doc-type-light.svg
  replay-by-doc-type-dark.svg
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

REPO = Path(__file__).resolve().parent.parent
REPLAY_SCRIPT = REPO / "scripts" / "eval_offline_replay.py"
DEFAULT_OUT_DIR = REPO / "docs" / "assets" / "eval"
REPLAY_FLOOR = "0.85"
FILE_STEM = "replay-by-doc-type"

# eval_offline_replay.py has used both spellings for the same weighted field-level score.
COMBINED_KEYS = ("field_acc_combined", "extraction_f1_combined")
PER_TYPE_SCORE_KEYS = ("field_acc", "f1")

FONT = "system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"

THEMES: dict[str, dict[str, str]] = {
    "light": {"text": "#1f2328", "muted": "#59636e", "grid": "#d1d9e0", "dot": "#0e7490"},
    "dark": {"text": "#e6edf3", "muted": "#9198a1", "grid": "#3d444d", "dot": "#06B6D4"},
}

TITLE = "Offline replay by document type"
FOOTER = "Source: scripts/eval_offline_replay.py. Regenerate: python scripts/render_eval_chart.py"

# Layout (px)
WIDTH = 720
PAD = 24
ROW_H = 28
PLOT_TOP = 96
PLOT_RIGHT = 630
VALUE_X = WIDTH - PAD
CHAR_W = 7.4  # rough average glyph width at 13px, used to size the label column
MIN_LABEL_W = 176
TICK_STEP = 0.05


class ReplayFormatError(ValueError):
    """Raised when the replay JSON lacks a key the chart needs."""


@dataclass(frozen=True)
class Row:
    label: str
    score: float
    is_total: bool = False


@dataclass(frozen=True)
class ChartData:
    rows: tuple[Row, ...]
    floor: float
    replayed: int
    pending: int
    corpus: int


def _require(mapping: dict, key: str, where: str) -> object:
    if not isinstance(mapping, dict) or key not in mapping:
        raise ReplayFormatError(f"replay JSON is missing '{key}' in {where}")
    return mapping[key]


def _score(mapping: dict, keys: tuple[str, ...], where: str) -> float:
    for key in keys:
        if isinstance(mapping, dict) and key in mapping:
            return float(mapping[key])
    raise ReplayFormatError(f"replay JSON is missing one of {', '.join(keys)} in {where}")


def parse_replay(summary: dict) -> ChartData:
    """Turn an eval_offline_replay.py summary into sorted chart rows."""
    replayed = int(_require(summary, "replayed", "the top level"))
    pending = int(_require(summary, "pending_fixtures", "the top level"))
    corpus = int(_require(summary, "corpus_cases", "the top level"))
    floor = float(_require(summary, "floor", "the top level"))
    combined = _score(summary, COMBINED_KEYS, "the top level")
    per_type = _require(summary, "per_doc_type", "the top level")
    if not isinstance(per_type, dict) or not per_type:
        raise ReplayFormatError("replay JSON has an empty or invalid 'per_doc_type'")

    keyed: list[tuple[float, str, Row]] = []
    for doc_type, stats in per_type.items():
        where = f"per_doc_type['{doc_type}']"
        count = int(_require(stats, "count", where))
        score = _score(stats, PER_TYPE_SCORE_KEYS, where)
        keyed.append((-round(score, 4), str(doc_type), Row(f"{doc_type} (n={count})", score)))
    typed = [row for *_, row in sorted(keyed, key=lambda item: item[:2])]

    rows = (Row(f"all fixtures (n={replayed})", combined, is_total=True), *typed)
    return ChartData(rows=rows, floor=floor, replayed=replayed, pending=pending, corpus=corpus)


def axis_lo(data: ChartData) -> float:
    """Lower axis bound: one tick below the 0.05 step at or under the smallest value."""
    smallest = min([r.score for r in data.rows] + [data.floor])
    steps = math.floor(round(smallest * 20, 9))
    return round(steps / 20 - TICK_STEP, 2)


def _fmt(value: float) -> str:
    return f"{value:.1f}"


def _floor_text(floor: float) -> str:
    return format(floor, "g")


def render_svg(data: ChartData, theme: str) -> str:
    colors = THEMES[theme]
    lo, hi = axis_lo(data), 1.0
    longest = max(len(r.label) for r in data.rows)
    plot_left = PAD + max(MIN_LABEL_W, math.ceil(longest * CHAR_W)) + 16
    span = PLOT_RIGHT - plot_left

    def x_of(value: float) -> float:
        return plot_left + (value - lo) / (hi - lo) * span

    n = len(data.rows)
    plot_bottom = PLOT_TOP + n * ROW_H
    tick_y = plot_bottom + 18
    caption_y = tick_y + 22
    footer_y = caption_y + 26
    height = footer_y + PAD - 8

    subtitle = (
        f"{data.replayed} committed fixtures, {data.pending} of {data.corpus} lookup cases "
        "pending. Deterministic, no API calls."
    )
    caption = f"weighted field-level accuracy (axis starts at {lo:.2f})"
    floor_label = f"CI floor {_floor_text(data.floor)}"
    desc_rows = "; ".join(f"{r.label} {r.score:.4f}" for r in data.rows)
    desc = (
        f"Dot chart of weighted field-level accuracy from the offline replay of "
        f"{data.replayed} committed fixtures: {desc_rows}. {floor_label}. "
        f"Axis runs from {lo:.2f} to {hi:.2f}."
    )

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" role="img" aria-labelledby="title desc" '
        f'font-family="{FONT}">',
        f'  <title id="title">{escape(TITLE)}</title>',
        f'  <desc id="desc">{escape(desc)}</desc>',
        f'  <text x="{PAD}" y="34" font-size="17" font-weight="600" fill="{colors["text"]}">'
        f"{escape(TITLE)}</text>",
        f'  <text x="{PAD}" y="56" font-size="12.5" fill="{colors["muted"]}">'
        f"{escape(subtitle)}</text>",
    ]

    # Vertical gridlines and tick labels every 0.05.
    first_tick = round(lo * 20)
    for k in range(first_tick, 21):
        value = k / 20
        x = _fmt(x_of(value))
        out.append(
            f'  <line x1="{x}" y1="{PLOT_TOP}" x2="{x}" y2="{plot_bottom}" '
            f'stroke="{colors["grid"]}" stroke-width="1"/>'
        )
        out.append(
            f'  <text x="{x}" y="{tick_y}" font-size="11.5" text-anchor="middle" '
            f'fill="{colors["muted"]}">{value:.2f}</text>'
        )

    # CI floor marker.
    fx = _fmt(x_of(data.floor))
    out.append(
        f'  <line x1="{fx}" y1="{PLOT_TOP - 10}" x2="{fx}" y2="{plot_bottom}" '
        f'stroke="{colors["muted"]}" stroke-width="1.5" stroke-dasharray="4 3"/>'
    )
    out.append(
        f'  <text x="{fx}" y="{PLOT_TOP - 16}" font-size="11.5" text-anchor="middle" '
        f'fill="{colors["muted"]}">{escape(floor_label)}</text>'
    )

    # Rows: label, dot, value.
    for i, row in enumerate(data.rows):
        cy = PLOT_TOP + i * ROW_H + ROW_H / 2
        ty = _fmt(cy + 4.5)
        weight = ' font-weight="600"' if row.is_total else ""
        out.append(
            f'  <text x="{PAD}" y="{ty}" font-size="13"{weight} fill="{colors["text"]}">'
            f"{escape(row.label)}</text>"
        )
        if row.is_total:
            out.append(
                f'  <circle cx="{_fmt(x_of(row.score))}" cy="{_fmt(cy)}" r="7" '
                f'fill="{colors["dot"]}" stroke="{colors["text"]}" stroke-width="1.5"/>'
            )
        else:
            out.append(
                f'  <circle cx="{_fmt(x_of(row.score))}" cy="{_fmt(cy)}" r="5" '
                f'fill="{colors["dot"]}"/>'
            )
        out.append(
            f'  <text x="{VALUE_X}" y="{ty}" font-size="13"{weight} text-anchor="end" '
            f'font-variant-numeric="tabular-nums" fill="{colors["text"]}">{row.score:.4f}</text>'
        )
        if row.is_total and n > 1:
            sep = _fmt(PLOT_TOP + ROW_H)
            out.append(
                f'  <line x1="{PAD}" y1="{sep}" x2="{VALUE_X}" y2="{sep}" '
                f'stroke="{colors["grid"]}" stroke-width="1"/>'
            )

    out.append(
        f'  <text x="{_fmt((plot_left + PLOT_RIGHT) / 2)}" y="{caption_y}" font-size="12" '
        f'text-anchor="middle" fill="{colors["muted"]}">{escape(caption)}</text>'
    )
    out.append(
        f'  <text x="{PAD}" y="{footer_y}" font-size="11" fill="{colors["muted"]}">'
        f"{escape(FOOTER)}</text>"
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def render_all(summary: dict) -> dict[str, str]:
    """Return {filename: svg_text} for both themes."""
    data = parse_replay(summary)
    return {f"{FILE_STEM}-{theme}.svg": render_svg(data, theme) for theme in THEMES}


def run_replay() -> dict:
    """Run the offline replay into a temp dir and return its summary JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "replay.json"
        subprocess.run(
            [sys.executable, str(REPLAY_SCRIPT), "--floor", REPLAY_FLOOR, "--out", str(out)],
            check=True,
            capture_output=True,
        )
        return json.loads(out.read_text())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--in", dest="in_path", type=Path, help="render from an existing replay JSON")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument(
        "--check",
        action="store_true",
        help="render in memory and exit 1 if the files in --out-dir differ",
    )
    args = ap.parse_args(argv)

    summary = json.loads(args.in_path.read_text()) if args.in_path else run_replay()
    rendered = render_all(summary)

    if args.check:
        stale = [
            name
            for name, text in rendered.items()
            if not (args.out_dir / name).is_file()
            or (args.out_dir / name).read_bytes() != text.encode("utf-8")
        ]
        if stale:
            print(f"stale chart(s): {', '.join(stale)}; run python scripts/render_eval_chart.py")
            return 1
        print("charts match the replay output")
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in rendered.items():
        (args.out_dir / name).write_bytes(text.encode("utf-8"))
        print(f"wrote {args.out_dir / name}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
