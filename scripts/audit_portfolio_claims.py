from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METRICS_PATH = ROOT / "docs" / "portfolio-metrics.yaml"

DOC_PATHS = [
    ROOT / "README.md",
    ROOT / "CASE_STUDY.md",
    ROOT / "offer-kit.yaml",
    *sorted((ROOT / "docs").glob("**/*.md")),
]

EXCLUDED_DOC_PARTS = {
    "docs/specs",
}

STALE_PATTERNS = {
    "1,155": "Use 1,260 collected tests or 1,253 passed from docs/portfolio-metrics.yaml.",
    "1,185": "Use 1,260 collected tests or 1,253 passed from docs/portfolio-metrics.yaml.",
    "94.6%": "Use 95.5% accepted F1 baseline, with its 28-case source.",
    "74-case": "Use 72-case scored eval corpus.",
    "74 cases": "Use 72 scored eval cases.",
    "52 golden": "Use 51 golden cases.",
    "22 adversarial": "Use 21 adversarial cases.",
    "90%+": "Use the current 81.54% local coverage result and 80% gate.",
}


@dataclass(frozen=True)
class PortfolioMetrics:
    collected_tests: int
    latest_passed: int
    latest_skipped: int
    latest_deselected: int
    latest_coverage_percent: float
    coverage_gate_percent: int
    golden_cases: int
    adversarial_cases: int
    total_cases: int
    promptfoo_cases: int
    extraction_f1_percent: float


def _extract_number(text: str, key: str, cast=int):
    match = re.search(rf"^\s*{re.escape(key)}:\s*([0-9.]+)", text, re.MULTILINE)
    if not match:
        raise ValueError(f"Missing {key} in metrics file")
    return cast(match.group(1))


def _extract_latest_result(text: str) -> tuple[int, int, int]:
    match = re.search(
        r'latest_result:\s*"(\d+) passed, (\d+) skipped, (\d+) deselected"', text
    )
    if not match:
        raise ValueError("Missing latest_result in metrics file")
    return tuple(int(part) for part in match.groups())


def load_metrics(path: Path = DEFAULT_METRICS_PATH) -> PortfolioMetrics:
    text = path.read_text()
    passed, skipped, deselected = _extract_latest_result(text)
    return PortfolioMetrics(
        collected_tests=_extract_number(text, "collected_tests"),
        latest_passed=passed,
        latest_skipped=skipped,
        latest_deselected=deselected,
        latest_coverage_percent=_extract_number(text, "latest_coverage_percent", float),
        coverage_gate_percent=_extract_number(text, "coverage_gate_percent"),
        golden_cases=_extract_number(text, "golden_cases"),
        adversarial_cases=_extract_number(text, "adversarial_cases"),
        total_cases=_extract_number(text, "total_cases"),
        promptfoo_cases=_extract_number(text, "promptfoo_cases"),
        extraction_f1_percent=_extract_number(text, "value_percent", float),
    )


def count_jsonl_cases(path: Path, *, skip_meta: bool = True) -> int:
    count = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if skip_meta and "_meta" in record:
            continue
        count += 1
    return count


def actual_counts(root: Path = ROOT) -> dict[str, int]:
    golden = count_jsonl_cases(root / "evals" / "golden_set.jsonl")
    adversarial = count_jsonl_cases(root / "evals" / "adversarial_set.jsonl")
    promptfoo = count_jsonl_cases(root / "evals" / "promptfoo_tests.jsonl", skip_meta=False)
    return {
        "golden_cases": golden,
        "adversarial_cases": adversarial,
        "total_cases": golden + adversarial,
        "promptfoo_cases": promptfoo,
    }


def _is_excluded(path: Path) -> bool:
    try:
        rel = path.relative_to(ROOT).as_posix()
    except ValueError:
        return False
    return any(rel.startswith(part) for part in EXCLUDED_DOC_PARTS)


def scan_docs(paths: list[Path] | None = None) -> list[str]:
    findings: list[str] = []
    for path in paths or DOC_PATHS:
        if not path.exists() or _is_excluded(path):
            continue
        text = path.read_text(errors="ignore")
        try:
            rel = path.relative_to(ROOT)
        except ValueError:
            rel = path
        for needle, message in STALE_PATTERNS.items():
            if needle in text:
                findings.append(f"{rel}: stale claim {needle!r}. {message}")
    return findings


def validate_metrics(metrics: PortfolioMetrics, root: Path = ROOT) -> list[str]:
    counts = actual_counts(root)
    findings: list[str] = []
    for key, actual in counts.items():
        expected = getattr(metrics, key)
        if actual != expected:
            findings.append(f"{key}: expected {expected}, found {actual}")
    if metrics.latest_passed + metrics.latest_skipped + metrics.latest_deselected != metrics.collected_tests:
        findings.append(
            "testing.latest_result does not add up to testing.collected_tests: "
            f"{metrics.latest_passed} + {metrics.latest_skipped} + "
            f"{metrics.latest_deselected} != {metrics.collected_tests}"
        )
    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit hiring-facing portfolio metric claims.")
    parser.add_argument(
        "--metrics",
        type=Path,
        default=DEFAULT_METRICS_PATH,
        help="Path to docs/portfolio-metrics.yaml.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    metrics = load_metrics(args.metrics)
    findings = validate_metrics(metrics) + scan_docs()
    if findings:
        for finding in findings:
            print(f"FAIL: {finding}")
        return 1
    print("portfolio claims audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
