"""Local held-out runner preparation. No live provider adapter or live CLI."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import math
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

LOG = logging.getLogger(__name__)
REPO = Path("/Users/cave/Projects/clients/docextract")
SOURCE_SHA = "09a690bc9efc873ee59725c685a2ec604b6ef247"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_module(name, relative):
    """Load pure scoring/pricing files without app settings or .env imports."""
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scoring = source_module("heldout_scoring", "autoresearch/eval.py")
pricing = source_module("heldout_pricing", "app/services/cost_tracker.py")


def load_partition(manifest_path):
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    root = manifest_path.parent
    for name in ("test", "train_dev"):
        p = root / manifest[name + "_path"]
        if (
            p.resolve().parent != root.resolve()
            or digest(p) != manifest[name + "_sha256"]
        ):
            raise ValueError("Partition path or hash mismatch: " + name)
    for relative, sha in manifest["source_hashes"].items():
        if digest(REPO / relative) != sha:
            raise ValueError("Source or prompt changed: " + relative)
    cases = json.loads((root / manifest["test_path"]).read_text())
    if len(cases) != manifest["test_case_count"] or not cases:
        raise ValueError("Invalid declared denominator")
    seen = set()
    for case in cases:
        if case["id"] in seen or case["weight"] != 1 or not case["expected"]:
            raise ValueError("Invalid case identity, weight or expected fields")
        seen.add(case["id"])
    return manifest, cases


def priced_traces(traces, allowed):
    total = Decimal("0")
    complete = bool(traces)
    tracker = pricing.CostTracker()
    for tr in traces:
        model, it, ot = tr.get("model"), tr.get("input_tokens"), tr.get("output_tokens")
        valid = (
            model in allowed
            and model in pricing.COST_PER_1K_TOKENS
            and type(it) is int
            and type(ot) is int
            and it >= 0
            and ot >= 0
            and not tr.get("cache_creation_tokens")
            and not tr.get("cache_read_tokens")
            and tr.get("retries", 0) == 0
        )
        if not valid:
            complete = False
            continue
        total += tracker.compute_cost(
            model,
            it,
            ot,
            tr.get("operation", "extract"),
            float(tr.get("latency_ms") or 0),
        ).total_cost_usd
    return total, complete


def save(path, artifact):
    """Persist only inside the new isolated run directory."""
    Path(path).write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\n")


async def run(
    manifest_path,
    output_dir,
    adapter,
    *,
    budget,
    allowed_models,
    metadata,
    price_attempts=None,
):
    """Adapter owns extract/clear/traces/bound and complete provider-call accounting.

    The fake adapter is the only implemented adapter. A future live adapter must
    enforce a proven call/token bound including SDK and Instructor retries.
    """
    manifest, cases = load_partition(manifest_path)
    budget = Decimal(str(budget))
    if not budget.is_finite() or budget <= 0 or not allowed_models:
        raise ValueError("Explicit positive budget and allowed models required")
    if adapter.kind != "fake":
        raise ValueError("Live adapter is not enabled in this local preparation")
    output_dir = Path(output_dir).resolve()
    if output_dir.is_relative_to(REPO.resolve()):
        raise ValueError("Run artifacts must be outside the source repository")
    output_dir.mkdir(parents=True, exist_ok=False)
    out = output_dir / "run.json"
    artifact = dict(
        status="FAKE VERIFICATION ONLY, PERFORMANCE UNMEASURED",
        source_git_sha=SOURCE_SHA,
        metadata=metadata,
        started_at=datetime.now(timezone.utc).isoformat(),
        command=list(sys.argv),
        artifact_path=str(out),
        partition_manifest_sha256=digest(manifest_path),
        test_sha256=manifest["test_sha256"],
        source_hashes=manifest["source_hashes"],
        budget_usd=str(budget),
        allowed_models=list(allowed_models),
        pricing_status="Historical repository table, fake tests only; reverify before funding",
        case_count=len(cases),
        per_case=[],
        cost_usd=None,
        priced_subtotal_usd="0",
        primary_metric="weighted_field_level_accuracy",
        primary_score=None,
        completion_count=0,
        stop_reason=None,
    )
    spent = Decimal("0")
    cancelled = False
    save(out, artifact)
    for case in cases:
        bound = adapter.bound(case)
        if (
            bound is None
            or not Decimal(str(bound)).is_finite()
            or Decimal(str(bound)) <= 0
        ):
            artifact["stop_reason"] = "No safe bound for all provider calls"
            break
        bound = Decimal(str(bound))
        if spent + bound > budget:
            artifact["stop_reason"] = "Insufficient remaining budget before next case"
            break
        adapter.clear()
        start = time.perf_counter()
        row = dict(
            id=case["id"],
            weight=case["weight"],
            score=0.0,
            prediction=None,
            model_used=None,
            error=None,
        )
        try:
            result = await adapter.extract(case["input_text"], case["doc_type"])
            row.update(
                prediction=result.data,
                model_used=result.model_used,
                corrections_applied=result.corrections_applied,
                reflection_applied=result.reflection_applied,
            )
            if (
                not result.schema_valid
                or not result.model_used
                or result.model_used not in allowed_models
            ):
                raise ValueError("Invalid schema or unverified model identity")
            row["score"] = scoring.score_extraction(
                result.data, case["expected"], case["critical_fields"]
            )
            artifact["completion_count"] += 1
        except asyncio.CancelledError:
            cancelled = True
            LOG.warning("Extraction cancelled for %s", case["id"])
            row["error"] = "CancelledError"
            artifact["stop_reason"] = "Cancelled; partial artifact retained"
        except Exception as exc:
            LOG.warning("Extraction failed for %s: %s", case["id"], type(exc).__name__)
            row["error"] = type(exc).__name__ + ": " + str(exc)
        row["latency_ms"] = (time.perf_counter() - start) * 1000
        row["traces"] = adapter.traces()
        price = price_attempts or priced_traces
        cost, complete = price(row["traces"], allowed_models)
        complete = complete and adapter.accounting_complete
        row.update(
            priced_subtotal_usd=str(cost),
            cost_complete=complete,
            cost_usd=str(cost) if complete else None,
        )
        spent += cost
        artifact["per_case"].append(row)
        artifact["priced_subtotal_usd"] = str(spent)
        if not complete:
            artifact["stop_reason"] = (
                "Missing, unpriced or incomplete provider-call accounting"
            )
        elif cost > bound:
            artifact["stop_reason"] = "Call bound violated; no further cases permitted"
        save(out, artifact)
        if artifact["stop_reason"]:
            break
    rows = artifact["per_case"]
    full = len(rows) == len(cases)
    # Failed and unattempted cases remain in the declared denominator.
    artifact["declared_denominator_score"] = sum(
        r["score"] * r["weight"] for r in rows
    ) / sum(c["weight"] for c in cases)
    if full:
        artifact["primary_score"] = artifact["declared_denominator_score"]
    if rows and all(r["cost_complete"] for r in rows):
        artifact["cost_usd"] = str(spent)
    observations = sorted(r["latency_ms"] for r in rows)
    artifact["latency"] = dict(
        observations_ms=[r["latency_ms"] for r in rows],
        percentile_method="nearest rank",
        p50_ms=observations[math.ceil(0.5 * len(observations)) - 1]
        if observations
        else None,
        p95_ms=observations[math.ceil(0.95 * len(observations)) - 1]
        if observations
        else None,
        coverage="complete" if full else "partial",
    )
    artifact["ended_at"] = datetime.now(timezone.utc).isoformat()
    save(out, artifact)
    if cancelled:
        raise asyncio.CancelledError()
    return artifact
