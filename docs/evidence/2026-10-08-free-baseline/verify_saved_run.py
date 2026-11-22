"""Verify the frozen saved baseline offline. Never invokes a model or application."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import types

RUN_SHA = "9ba5b31ebb6b744d80e3a95e6e1901b2308f2902e41bf96f32be1897de906e5e"
TEST_SHA = "944de5eb5bfa55f04662afcf4d7331f8e19e097f4218c49acdf94702012752f8"
SCORER_SHA = "f6c684917c3a5aa5407354c106ca479fcd7c519db64ca16511203c013b4346e8"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def verify_saved_run(package_dir: Path) -> dict:
    """Check original bytes, saved trace bindings and scores; human review is separate."""
    root = Path(package_dir).resolve()
    manifest = json.loads((root / "manifest.json").read_bytes())
    files = manifest["files"]
    required = {
        "baseline/run.json",
        "corpus/test.json",
        "corpus/train_dev.json",
        "corpus/partition_manifest.json",
        "source/autoresearch/eval.py",
        *(f"baseline/attempt-{i:03}.json" for i in range(1, 13)),
    }
    if not required <= files.keys():
        raise ValueError("Required evidence missing from manifest")
    payloads = {}
    for relative, entry in files.items():
        candidate = Path(relative)
        path = (root / candidate).resolve()
        if (
            candidate.is_absolute()
            or ".." in candidate.parts
            or not path.is_relative_to(root)
        ):
            raise ValueError("Unsafe manifest path")
        data = path.read_bytes()
        if digest(data) != entry["sha256"]:
            raise ValueError("Manifest hash mismatch: " + relative)
        payloads[relative] = data
    if digest(payloads["baseline/run.json"]) != RUN_SHA:
        raise ValueError("Historical run changed")
    if digest(payloads["corpus/test.json"]) != TEST_SHA:
        raise ValueError("Historical reference labels changed")
    if digest(payloads["source/autoresearch/eval.py"]) != SCORER_SHA:
        raise ValueError("Scorer differs from historical source")
    run = json.loads(payloads["baseline/run.json"])
    cases = json.loads(payloads["corpus/test.json"])
    for relative, expected in run["source_hashes"].items():
        if digest(payloads.get("source/" + relative, b"")) != expected:
            raise ValueError("Required bound source changed: " + relative)
    for original, expected in run["frozen"]["files"].items():
        if "/measurement/" not in original:
            # The interpreter is recorded but not redistributed in this source package.
            continue
        relative = original.split("/measurement/", 1)[1]
        exported = (
            "corpus/partition_manifest.json"
            if relative == "partition_manifest.json"
            else "protocol/" + relative
        )
        if digest(payloads.get(exported, b"")) != expected:
            raise ValueError("Historical binding mismatch: " + exported)
    integration_hashes = run["frozen"]["integration_source_hashes"]
    for relative, expected in integration_hashes.items():
        exported = "source/" + relative
        required_export = "/schemas/" in relative or relative.endswith(
            "injection_guard.py"
        )
        if (required_export or exported in payloads) and digest(
            payloads.get(exported, b"")
        ) != expected:
            raise ValueError("Historical binding mismatch: " + exported)
    binding = json.loads(payloads["protocol/EXECUTION-BINDING.json"])
    if binding["source_hashes"] != integration_hashes:
        raise ValueError("Historical binding inventory differs")
    for relative, key in [
        ("corpus/train_dev.json", "train_dev_sha256"),
        ("corpus/partition_manifest.json", "partition_manifest_sha256"),
    ]:
        if digest(payloads[relative]) != run[key]:
            raise ValueError("Partition binding changed")
    rows = run["per_case"]
    if len(cases) != 12 or len(rows) != 12 or len({c["id"] for c in cases}) != 12:
        raise ValueError("Incomplete case coverage")
    if [r["id"] for r in rows] != [c["id"] for c in cases]:
        raise ValueError("Case identity or order changed")
    scorer = types.ModuleType("_bound_saved_scorer")
    scorer.__file__ = str(root / "source/autoresearch/eval.py")
    old_path = sys.path[:]
    old_module = sys.modules.get(scorer.__name__)
    sys.modules[scorer.__name__] = scorer
    try:
        exec(
            compile(payloads["source/autoresearch/eval.py"], scorer.__file__, "exec"),
            scorer.__dict__,
        )
        scores = []
        latencies = []
        for index, (case, row) in enumerate(zip(cases, rows), start=1):
            attempt = json.loads(payloads[f"baseline/attempt-{index:03}.json"])
            if attempt != row:
                raise ValueError("Attempt receipt differs from saved run")
            for field, hash_key in [
                ("prediction", "prediction_sha256"),
                ("request_body", "request_sha256"),
                ("response", "filtered_response_sha256"),
            ]:
                if digest(encoded(row[field])) != row[hash_key]:
                    raise ValueError("Saved trace binding mismatch: " + hash_key)
            score = scorer.score_extraction(
                row["prediction"], case["expected"], case["critical_fields"]
            )
            if not math.isclose(score, row["score"], rel_tol=0, abs_tol=1e-12):
                raise ValueError("Recomputed score differs")
            if case["weight"] != row["weight"] or row["error"] is not None:
                raise ValueError("Denominator or case status differs")
            scores.append((score, case["weight"]))
            latencies.append(row["latency_ms"])
        total = sum(score * weight for score, weight in scores) / sum(
            weight for _, weight in scores
        )
        if not math.isclose(total, run["primary_score"], rel_tol=0, abs_tol=1e-12):
            raise ValueError("Aggregate score differs")
    finally:
        sys.path[:] = old_path
        if old_module is None:
            sys.modules.pop(scorer.__name__, None)
        else:
            sys.modules[scorer.__name__] = old_module
    latencies.sort()
    return {
        "status": "saved machine evidence verified",
        "run_sha256": RUN_SHA,
        "case_count": len(cases),
        "weighted_reference_field_score": total,
        "latency_p50_ms": latencies[math.ceil(len(latencies) * 0.5) - 1],
        "latency_p95_ms": latencies[math.ceil(len(latencies) * 0.95) - 1],
        "response_reported_cost_usd": run["cost_usd"],
        "human_review_status": "not verified by this reader",
        "scope": "Saved scores and filtered receipt bindings only. No fresh schema validation, inference, production or current-main claim.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "package_dir", nargs="?", type=Path, default=Path(__file__).resolve().parent
    )
    args = parser.parse_args()
    try:
        result = verify_saved_run(args.package_dir)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print("Verification failed: " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
