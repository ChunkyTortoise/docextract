#!/usr/bin/env python3
"""Check that every metric-shaped claim in a markdown file has a matching
status=measured entry in the portfolio metrics ledger.

Usage:
    python scripts/check_metrics_ledger.py <markdown_file> [--ledger <yaml_file>]

Exit codes:
    0  All metric claims are backed by a status=measured ledger row.
    1  One or more metric claims lack a measured backing, or an argument error occurred.

Metric-shaped claim pattern (matches ISO-style metric tokens):
    digits (with optional comma/period separators) followed by one of:
    ms, s, %, QPS, qps, req/s, $/doc

A claim matches a ledger row if the row's 'value' field (case-insensitive, whitespace-
normalised) equals or contains the extracted metric token AND the row's status is
'measured'. A claim also matches if the row's 'id' appears as a substring in the
surrounding markdown line.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

# Default ledger location relative to this script (scripts/ -> docs/portfolio-metrics.yaml)
_DEFAULT_LEDGER = Path(__file__).parents[1] / "docs" / "portfolio-metrics.yaml"

# Matches: 123ms, 4.1s, 95.5%, 250QPS, 250 QPS, $0.03/doc, 1200req/s, etc.
_METRIC_RE = re.compile(
    r"(?:\$\d[\d,.]*/doc|\d[\d,.]* *(?:ms|s(?!\w)|%|QPS|qps|req/s))",
    re.IGNORECASE,
)


def _load_ledger(ledger_path: Path) -> list[dict]:
    """Load metrics list from the YAML ledger. Supports both 'metrics' list (v2)
    and legacy 'quality_claims' dict (v1)."""
    with ledger_path.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return []
    # Prefer the new 'metrics' list
    if "metrics" in data and isinstance(data["metrics"], list):
        return data["metrics"]
    # Fall back to legacy quality_claims dict
    if "quality_claims" in data and isinstance(data["quality_claims"], dict):
        entries = []
        for key, val in data["quality_claims"].items():
            if isinstance(val, dict):
                raw_value = str(val.get("value") or val.get("value_percent", ""))
                entries.append(
                    {
                        "id": key,
                        "value": raw_value,
                        "status": val.get("status") or val.get("basis", "modeled"),
                    }
                )
        return entries
    return []


def _normalise(s: str) -> str:
    return re.sub(r"\s+", "", s.lower())


def check_file(md_path: Path, ledger_path: Path) -> list[str]:
    """Return a list of error messages. Empty list means all claims are backed."""
    ledger_entries = _load_ledger(ledger_path)

    # Build lookup: normalised_value -> status, and id -> status
    value_status: dict[str, str] = {}
    id_status: dict[str, str] = {}
    for entry in ledger_entries:
        val = _normalise(str(entry.get("value", "")))
        if val:
            value_status[val] = str(entry.get("status", "modeled")).lower()
        eid = str(entry.get("id", "")).strip()
        if eid:
            id_status[eid] = str(entry.get("status", "modeled")).lower()

    text = md_path.read_text()
    errors: list[str] = []

    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in _METRIC_RE.finditer(line):
            token = match.group(0)
            normalised_token = _normalise(token)

            # Check value match
            status = value_status.get(normalised_token)
            if status == "measured":
                continue

            # Check id match: any id that appears on the same line
            id_hit = next(
                (id_status[eid] for eid in id_status if eid in line.lower()),
                None,
            )
            if id_hit == "measured":
                continue

            if status == "modeled":
                errors.append(
                    f"{md_path}:{line_no}: metric '{token}' is backed only by a"
                    f" 'modeled' ledger row — must be 'measured' before citing in docs"
                )
            else:
                errors.append(
                    f"{md_path}:{line_no}: metric '{token}' has no matching"
                    f" status=measured ledger row"
                )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("markdown_file", type=Path, help="Markdown file to check")
    parser.add_argument(
        "--ledger",
        type=Path,
        default=_DEFAULT_LEDGER,
        help=f"Path to portfolio-metrics.yaml (default: {_DEFAULT_LEDGER})",
    )
    args = parser.parse_args(argv)

    if not args.markdown_file.exists():
        print(f"error: markdown file not found: {args.markdown_file}", file=sys.stderr)
        return 1
    if not args.ledger.exists():
        print(f"error: ledger file not found: {args.ledger}", file=sys.stderr)
        return 1

    errors = check_file(args.markdown_file, args.ledger)
    for err in errors:
        print(err)
    if errors:
        print(f"\n{len(errors)} metric claim(s) lack a measured ledger backing.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
