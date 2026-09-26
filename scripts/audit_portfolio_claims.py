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
    *sorted((ROOT / "docs").glob("**/*.md")),
]

EXCLUDED_DOC_PARTS: set[str] = set()

STALE_PATTERNS = {
    "1,155": "Test counts are not a public claim; cite the 80% coverage gate only.",
    "1,185": "Test counts are not a public claim; cite the 80% coverage gate only.",
    "94.6%": "Use 95.5% (0.9555) case-weighted field-level replay score.",
    "74-case": "The replay lookup set is 72 cases (28 replayed, 44 pending).",
    "74 cases": "The replay lookup set is 72 cases (28 replayed, 44 pending).",
    "52 golden": "The authoring corpus is 150 golden + 50 adversarial (200 cases in 202 lines).",
    "22 adversarial": "The authoring corpus is 150 golden + 50 adversarial (200 cases in 202 lines).",
    "151 golden": "The authoring corpus is 150 golden + 50 adversarial (200 cases in 202 lines).",
    "51 adversarial": "The authoring corpus is 150 golden + 50 adversarial (200 cases in 202 lines).",
    "90%+": "Use the 80% coverage gate.",
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


def _extract_number(text: str, key: str, cast=int, default=None):
    match = re.search(rf"^\s*{re.escape(key)}:\s*([0-9.]+)", text, re.MULTILINE)
    if not match:
        if default is not None:
            return default
        raise ValueError(f"Missing {key} in metrics file")
    return cast(match.group(1))


def _extract_latest_result(text: str) -> tuple[int, int, int]:
    match = re.search(
        r'latest_result:\s*"(\d+) passed, (\d+) skipped, (\d+) deselected"', text
    )
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())


def load_metrics(path: Path = DEFAULT_METRICS_PATH) -> PortfolioMetrics:
    text = path.read_text()
    passed, skipped, deselected = _extract_latest_result(text)
    return PortfolioMetrics(
        collected_tests=_extract_number(text, "collected_tests", default=0),
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
    if metrics.collected_tests and metrics.latest_passed + metrics.latest_skipped + metrics.latest_deselected != metrics.collected_tests:
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
    try:
        metrics = load_metrics(args.metrics)
    except OSError as e:
        print(f"FAIL: cannot read metrics file {args.metrics}: {e}")
        print("     Pass --metrics <path> (default: docs/portfolio-metrics.yaml).")
        return 2
    except ValueError as e:
        print(f"FAIL: metrics file {args.metrics} is missing or malformed: {e}")
        print(
            "     Expected keys: testing.latest_result, testing.collected_tests, "
            "testing.latest_coverage_percent, eval_corpus case counts, "
            "metrics.value_percent."
        )
        return 2
    try:
        findings = validate_metrics(metrics) + scan_docs()
    except (OSError, ValueError) as e:
        print(f"FAIL: audit could not complete: {e}")
        return 2
    if findings:
        for finding in findings:
            print(f"FAIL: {finding}")
        return 1
    print("portfolio claims audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
