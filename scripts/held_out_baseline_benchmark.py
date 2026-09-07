"""Held-out two-pass vs Pass-1-only benchmark scaffold (CONT-RA10).

STATUS: BENCHMARK PLAN / HARNESS ONLY — PERFORMANCE UNMEASURED

Default / --dry-run / --scaffold-only prints the comparison table schema and
exits 0 with no API calls. Live runs require a key, an explicit funding flag,
and a non-empty locked test partition. Do not invent accuracy numbers.

    python scripts/held_out_baseline_benchmark.py
    python scripts/held_out_baseline_benchmark.py --dry-run
    python scripts/held_out_baseline_benchmark.py --scaffold-only
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from autoresearch.eval import score_extraction  # noqa: E402

STATUS = "BENCHMARK PLAN / HARNESS ONLY — PERFORMANCE UNMEASURED"
DEFAULT_DATASET = REPO / "evals" / "held_out_live" / "test.json"
DEFAULT_MANIFEST = REPO / "evals" / "held_out_live" / "partition_manifest.json"
PROMPTS_PATH = REPO / "autoresearch" / "prompts.yaml"
ARTIFACT_ROOT = REPO / "docs" / "artifacts" / "held-out-baseline"

RUNNERS: dict[str, dict[str, Any]] = {
    "full": {
        "correction": True,
        "label": "two-pass (pass-1 + correction when below threshold)",
    },
    "simple": {
        "correction": False,
        "label": "pass-1 only (no correction pass)",
    },
}

COMPARISON_METRICS = (
    "field_accuracy_overall",
    "critical_field_failure_rate",
    "document_type_breakdown",
    "invalid_or_missing_outputs",
    "abstention_low_confidence_frequency",
    "e2e_latency_per_doc_incl_retries",
    "model_cost_per_doc_incl_retries",
)

RECORD_FIELDS = (
    "model_ids",
    "prompt_version",
    "document_provenance",
    "git_sha",
    "date",
    "command",
    "artifact_path",
    "run_conditions",
)

METRIC_TABLE_ROWS = (
    ("Field accuracy (overall, weighted)", "field_accuracy_overall"),
    ("Critical-field failure rate", "critical_field_failure_rate"),
    ("Document-type breakdown", "document_type_breakdown"),
    ("Invalid / missing outputs", "invalid_or_missing_outputs"),
    (
        "Abstention / low-confidence frequency among accepted outputs",
        "abstention_low_confidence_frequency",
    ),
    ("End-to-end latency per doc (including retries)", "e2e_latency_per_doc_incl_retries"),
    ("Model cost per doc (including retries)", "model_cost_per_doc_incl_retries"),
)


def load_prompts_meta(path: Path = PROMPTS_PATH) -> dict[str, Any]:
    """Return prompts.yaml version and confidence threshold params."""
    try:
        import yaml
    except ImportError:
        return {
            "version": None,
            "confidence_thresholds": {},
            "extraction_confidence_threshold": 0.8,
        }
    if not path.exists():
        return {
            "version": None,
            "confidence_thresholds": {},
            "extraction_confidence_threshold": 0.8,
        }
    data = yaml.safe_load(path.read_text()) or {}
    params = data.get("params") or {}
    return {
        "version": data.get("version"),
        "extraction_confidence_threshold": params.get("extraction_confidence_threshold", 0.8),
        "confidence_thresholds": dict(params.get("confidence_thresholds") or {}),
    }


def confidence_threshold_for(doc_type: str, prompts_meta: dict[str, Any]) -> float:
    thresholds = prompts_meta.get("confidence_thresholds") or {}
    fallback = float(prompts_meta.get("extraction_confidence_threshold") or 0.8)
    try:
        return float(thresholds.get(doc_type, fallback))
    except (TypeError, ValueError):
        return fallback


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dataset(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ValueError(f"held-out dataset must be a JSON array: {path}")
    return payload


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text())
    return payload if isinstance(payload, dict) else {}


def unmeasured_arm() -> dict[str, Any]:
    return {metric: "UNMEASURED" for metric in COMPARISON_METRICS}


def comparison_table_schema(
    full: dict[str, Any] | None = None,
    simple: dict[str, Any] | None = None,
) -> str:
    """Markdown comparison table. Defaults every cell to UNMEASURED."""
    full = full or unmeasured_arm()
    simple = simple or unmeasured_arm()
    lines = [
        "| Metric | full (two-pass) | simple (pass-1 only) | Delta (full − simple) |",
        "|---|---|---|---|",
    ]
    for label, key in METRIC_TABLE_ROWS:
        f_val = full.get(key, "UNMEASURED")
        s_val = simple.get(key, "UNMEASURED")
        delta = "UNMEASURED"
        lines.append(f"| {label} | {f_val} | {s_val} | {delta} |")
    return "\n".join(lines)


def record_fields_schema(values: dict[str, Any] | None = None) -> str:
    values = values or {}
    lines = ["| Record field | Value |", "|---|---|"]
    for field in RECORD_FIELDS:
        lines.append(f"| {field} | {values.get(field, 'UNMEASURED')} |")
    return "\n".join(lines)


def scaffold_report(
    *,
    dataset_path: Path,
    case_count: int,
    command: list[str],
    artifact_path: str,
) -> str:
    prompts_meta = load_prompts_meta()
    records = {
        "model_ids": "UNMEASURED",
        "prompt_version": prompts_meta.get("version"),
        "document_provenance": "UNMEASURED (partition not declared)",
        "git_sha": git_sha() or "UNMEASURED",
        "date": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "command": " ".join(command),
        "artifact_path": artifact_path,
        "run_conditions": "scaffold/dry-run; no API calls",
    }
    parts = [
        f"STATUS: {STATUS}",
        "",
        f"dataset: {dataset_path.relative_to(REPO) if dataset_path.is_relative_to(REPO) else dataset_path}",
        f"case_count: {case_count} (stubs are not a scored partition)",
        f"prompts.yaml version: {prompts_meta.get('version')}",
        f"runners: full={RUNNERS['full']['label']}; simple={RUNNERS['simple']['label']}",
        "scorer: autoresearch.eval.score_extraction",
        "Repeating offline replay does NOT satisfy this benchmark.",
        "",
        comparison_table_schema(),
        "",
        record_fields_schema(records),
        "",
        "Funding gate: docs/metering-runbook.md. Do not publish numbers until a",
        "logged artifact exists and Cayman has typed yes.",
    ]
    return "\n".join(parts) + "\n"


def critical_field_failures(
    extracted: dict[str, Any],
    expected: dict[str, Any],
    critical_fields: list[str],
) -> tuple[int, int]:
    """Return (failed, total) critical fields with non-null expected values."""
    failed = 0
    total = 0
    extracted = extracted or {}
    for key in critical_fields:
        if key not in expected:
            continue
        exp = expected[key]
        if exp is None or exp == []:
            continue
        total += 1
        field_score = score_extraction({key: extracted.get(key)}, {key: exp}, [key])
        if field_score < 1.0:
            failed += 1
    return failed, total


def weighted_accuracy(rows: list[dict[str, Any]]) -> float | None:
    scored = [r for r in rows if r.get("score") is not None]
    if not scored:
        return None
    tw = sum(float(r.get("weight") or 1.0) for r in scored)
    if tw == 0:
        return None
    return sum(float(r["score"]) * float(r.get("weight") or 1.0) for r in scored) / tw


def refuse_live(reason: str) -> int:
    print(f"STATUS: {STATUS}", file=sys.stderr)
    print(f"Refusing live API calls: {reason}", file=sys.stderr)
    print("See docs/held-out-baseline-benchmark.md and docs/metering-runbook.md.", file=sys.stderr)
    return 2


def _verify_partition(dataset_path: Path, manifest: dict[str, Any]) -> str | None:
    expected = manifest.get("test_sha256")
    if not expected:
        if not dataset_path.exists() or load_dataset(dataset_path) == []:
            return (
                "held-out test set is empty or undeclared. Add synthetic cases and "
                "lock hashes in evals/held_out_live/partition_manifest.json first "
                "(see evals/held_out_live/README.md)."
            )
        return "partition_manifest.json has no test_sha256; lock the partition before scoring."
    if not dataset_path.exists():
        return f"test dataset missing: {dataset_path}"
    actual = sha256_file(dataset_path)
    if actual != expected:
        return f"test.json sha256 {actual} != manifest test_sha256 {expected}"
    return None


async def _run_case(
    case: dict[str, Any],
    *,
    correction: bool,
    prompts_meta: dict[str, Any],
) -> dict[str, Any]:
    import time

    from app.services.claude_extractor import extract
    from app.services.cost_tracker import COST_PER_1K_TOKENS, CostTracker
    from app.services.llm_tracer import clear_in_memory_traces, get_in_memory_traces

    clear_in_memory_traces()
    tracker = CostTracker()
    t0 = time.perf_counter()
    try:
        result = await extract(case["input_text"], case["doc_type"], correction=correction)
        extracted = result.data or {}
        err = None
        schema_valid = bool(getattr(result, "schema_valid", True))
        confidence = float(getattr(result, "confidence", 0.0) or 0.0)
        model = getattr(result, "model_used", "") or ""
        corrections_applied = bool(getattr(result, "corrections_applied", False))
    except Exception as exc:  # record, never abort the sweep
        extracted, err = {}, f"{type(exc).__name__}: {exc}"
        schema_valid, confidence, model, corrections_applied = False, 0.0, "", False
    wall_ms = (time.perf_counter() - t0) * 1000.0

    cost_usd = 0.0
    for tr in get_in_memory_traces():
        it, ot, m = tr.get("input_tokens"), tr.get("output_tokens"), tr.get("model")
        if it is None or ot is None or m not in COST_PER_1K_TOKENS:
            continue
        rc = tracker.compute_cost(
            m, it, ot, tr.get("operation", "extract"), float(tr.get("latency_ms") or 0)
        )
        cost_usd += float(rc.total_cost_usd)

    invalid = bool(err) or not extracted or not schema_valid
    score = (
        None
        if invalid
        else score_extraction(
            extracted, case.get("expected") or {}, case.get("critical_fields") or []
        )
    )
    failed, total = critical_field_failures(
        extracted, case.get("expected") or {}, case.get("critical_fields") or []
    )
    threshold = confidence_threshold_for(case.get("doc_type") or "unknown", prompts_meta)
    accepted = not invalid
    low_conf = accepted and confidence < threshold
    return {
        "id": case.get("id"),
        "doc_type": case.get("doc_type"),
        "weight": case.get("weight", 1.0),
        "score": score,
        "invalid": invalid,
        "error": err,
        "confidence": confidence,
        "low_confidence": low_conf,
        "accepted": accepted,
        "critical_failed": failed,
        "critical_total": total,
        "latency_ms": round(wall_ms, 1),
        "cost_usd": round(cost_usd, 6),
        "model": model,
        "corrections_applied": corrections_applied,
        "correction_flag": correction,
    }


def summarize_arm(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return unmeasured_arm()
    n = len(rows)
    invalid_n = sum(1 for r in rows if r.get("invalid"))
    accepted = [r for r in rows if r.get("accepted")]
    low_conf_n = sum(1 for r in accepted if r.get("low_confidence"))
    crit_failed = sum(int(r.get("critical_failed") or 0) for r in rows)
    crit_total = sum(int(r.get("critical_total") or 0) for r in rows)
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_type[str(r.get("doc_type") or "unknown")].append(r)

    def _fmt_acc(val: float | None) -> str:
        return "UNMEASURED" if val is None else f"{val:.6f}"

    type_breakdown = {dt: _fmt_acc(weighted_accuracy(rs)) for dt, rs in sorted(by_type.items())}
    lat = [float(r["latency_ms"]) for r in rows]
    cost = [float(r["cost_usd"]) for r in rows]
    return {
        "field_accuracy_overall": _fmt_acc(weighted_accuracy(rows)),
        "critical_field_failure_rate": (
            "UNMEASURED" if crit_total == 0 else f"{crit_failed / crit_total:.6f}"
        ),
        "document_type_breakdown": type_breakdown,
        "invalid_or_missing_outputs": f"{invalid_n / n:.6f}",
        "abstention_low_confidence_frequency": (
            "UNMEASURED" if not accepted else f"{low_conf_n / len(accepted):.6f}"
        ),
        "e2e_latency_per_doc_incl_retries": {
            "mean_ms": round(sum(lat) / len(lat), 1) if lat else "UNMEASURED",
            "n": len(lat),
        },
        "model_cost_per_doc_incl_retries": {
            "mean_usd": round(sum(cost) / len(cost), 6) if cost else "UNMEASURED",
            "n": len(cost),
        },
    }


async def run_live(
    dataset: list[dict[str, Any]],
    prompts_meta: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for runner_id, spec in RUNNERS.items():
        rows = []
        for case in dataset:
            rows.append(
                await _run_case(
                    case, correction=bool(spec["correction"]), prompts_meta=prompts_meta
                )
            )
        out[runner_id] = rows
    return out


def write_artifact(payload: dict[str, Any]) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    dest_dir = ARTIFACT_ROOT / stamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "run.json"
    dest.write_text(json.dumps(payload, indent=2) + "\n")
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Held-out two-pass vs pass-1-only benchmark (unmeasured scaffold).",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="Held-out test JSON (default: evals/held_out_live/test.json)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Partition manifest JSON",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print table schema; no API calls")
    parser.add_argument(
        "--scaffold-only",
        action="store_true",
        help="Alias of --dry-run: print table schema; no API calls",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Attempt a funded live A/B run (refused without key, credit flag, and locked cases)",
    )
    parser.add_argument(
        "--confirm-credit-spend",
        action="store_true",
        help="Required with --live. Confirms Anthropic credit is authorized (see metering-runbook).",
    )
    args = parser.parse_args(argv)

    command = ["python", "scripts/held_out_baseline_benchmark.py", *(argv or sys.argv[1:])]
    dataset_path = args.dataset if args.dataset.is_absolute() else REPO / args.dataset
    case_count = len(load_dataset(dataset_path)) if dataset_path.exists() else 0

    if not args.live or args.dry_run or args.scaffold_only:
        print(
            scaffold_report(
                dataset_path=dataset_path,
                case_count=case_count,
                command=command,
                artifact_path="docs/artifacts/held-out-baseline/<YYYYMMDD>/run.json",
            ),
            end="",
        )
        return 0

    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return refuse_live("ANTHROPIC_API_KEY is not set. Funding is not authorized in CONT-RA10.")
    if not args.confirm_credit_spend:
        return refuse_live(
            "credit spend is not confirmed. docs/metering-runbook.md records "
            "credit balance too low; pass --confirm-credit-spend only after funding."
        )

    manifest = load_manifest(args.manifest if args.manifest.is_absolute() else REPO / args.manifest)
    partition_error = _verify_partition(dataset_path, manifest)
    if partition_error:
        return refuse_live(partition_error)

    dataset = load_dataset(dataset_path)
    prompts_meta = load_prompts_meta()
    arms = asyncio.run(run_live(dataset, prompts_meta))
    full_summary = summarize_arm(arms["full"])
    simple_summary = summarize_arm(arms["simple"])
    dest = write_artifact(
        {
            "status": STATUS,
            "date": datetime.now(UTC).isoformat(),
            "git_sha": git_sha(),
            "model_ids": sorted(
                {r.get("model") for rows in arms.values() for r in rows if r.get("model")}
            ),
            "prompt_version": prompts_meta.get("version"),
            "document_provenance": manifest.get("sources") or [],
            "command": command,
            "artifact_path": None,
            "run_conditions": {
                "runners": {k: v["correction"] for k, v in RUNNERS.items()},
                "confirm_credit_spend": True,
            },
            "partition_manifest_sha256": (
                sha256_file(args.manifest) if Path(args.manifest).exists() else None
            ),
            "test_sha256": sha256_file(dataset_path),
            "case_count": len(dataset),
            "primary_metric": "weighted_field_level_accuracy",
            "full": full_summary,
            "simple": simple_summary,
        }
    )
    # Re-write with final path once known.
    payload = json.loads(dest.read_text())
    payload["artifact_path"] = str(dest.relative_to(REPO))
    dest.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"STATUS: {STATUS}")
    print(comparison_table_schema(full_summary, simple_summary))
    print(f"wrote {dest.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
