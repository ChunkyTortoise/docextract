"""Anonymous free-model, single-pass extraction baseline.

This is not the Anthropic production pipeline and has no fallback, correction,
reflection, Instructor retry, deployment or database side effects. Test runs use
MockTransport only. Live sends require --live and a fresh zero-price catalog.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

import extractor_adapter
import runner

MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
ENDPOINT = "https://api.kilo.ai/api/gateway/chat/completions"
CATALOG = "https://api.kilo.ai/api/gateway/models"
ROOT = Path(__file__).resolve().parent


class AccountingError(ValueError):
    """Halt subsequent sends when identity or free accounting is unverified."""


def zero(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AccountingError("Missing or invalid zero price/cost") from exc
    if not number.is_finite() or number != 0 or isinstance(value, bool):
        raise AccountingError("Nonzero or invalid price/cost")


def check_catalog(data):
    matches = [m for m in data["data"] if m.get("id") == MODEL]
    if len(matches) != 1 or matches[0].get("isFree") is not True:
        raise AccountingError("Exact free model missing from public catalog")
    for key in ("prompt", "completion"):
        zero(matches[0]["pricing"].get(key))
    return matches[0]


def check_cost_details(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if "cost" in key.lower() and not isinstance(item, (dict, list)):
                zero(item)
            else:
                check_cost_details(item)
    elif isinstance(value, list):
        for item in value:
            check_cost_details(item)


def check_response(data):
    if data.get("model") != MODEL:
        raise AccountingError("Returned model identity mismatch")
    usage = data.get("usage", {})
    for key in ("prompt_tokens", "completion_tokens"):
        if type(usage.get(key)) is not int or usage[key] < 0:
            raise AccountingError("Missing or invalid token accounting")
    zero(usage.get("cost"))
    if usage.get("is_byok") is not False:
        raise AccountingError("Missing or invalid is_byok accounting")
    check_cost_details(usage.get("cost_details", {}))
    check_cost_details(data.get("cost_details", {}))


def encoded(data):
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def receipt(response):
    """Persist explicit fields only, omitting provider reasoning everywhere."""
    data = response.json()
    choices = data.get("choices", [])
    return dict(
        id=data.get("id"),
        model=data.get("model"),
        provider=data.get("provider"),
        usage=data.get("usage"),
        choices=[
            dict(
                finish_reason=c.get("finish_reason"),
                content=c.get("message", {}).get("content"),
            )
            for c in choices
        ],
    )


def request_body(module, case):
    doc_type = case["doc_type"]
    if doc_type not in ("invoice", "receipt", "purchase_order"):
        raise ValueError("Unsupported declared document type")
    schema = module.DOCUMENT_TYPE_MAP[doc_type]
    config, guard = module.prompt_config, module.injection_guard
    system = config.extract_system_prompt + guard.DEFENSE_SYSTEM_CLAUSE
    system += (
        "\nReturn only one JSON object matching this source schema. No Markdown.\n"
    )
    system += json.dumps(schema.model_json_schema(), sort_keys=True)
    user = config.extract_prompt.format(
        doc_type=doc_type,
        text=guard.wrap_untrusted(
            case["input_text"][: config.params.extract_text_limit]
        ),
    )
    return dict(
        model=MODEL,
        messages=[dict(role="system", content=system), dict(role="user", content=user)],
        max_tokens=4096,
        temperature=0,
        stream=False,
    )


def frozen_files(manifest_path):
    binding_path = ROOT / "EXECUTION-BINDING.json"
    binding = json.loads(binding_path.read_text())
    paths = [
        Path(manifest_path),
        ROOT / "runner.py",
        ROOT / "extractor_adapter.py",
        ROOT / "candidate/claude_extractor.py",
        binding_path,
        Path(__file__),
        Path(sys.executable),
    ]
    return dict(
        files={str(p): runner.digest(p) for p in paths},
        integration_source_hashes=binding["source_hashes"],
        python=platform.python_version(),
        httpx=httpx.__version__,
        runtime_executable=str(Path(sys.executable).resolve()),
    )


def guard_request(request):
    if (request.method, str(request.url)) not in {("GET", CATALOG), ("POST", ENDPOINT)}:
        raise AccountingError("Unexpected request method or endpoint")
    for header in ("authorization", "cookie", "proxy-authorization"):
        request.headers.pop(header, None)


def run(manifest_path, output_dir, *, transport=None, live=False):
    if transport is not None and not isinstance(transport, httpx.MockTransport):
        raise ValueError("Tests accept only MockTransport")
    if transport is None and not live:
        raise ValueError("Explicit live flag is required for network calls")
    if live and transport is not None:
        raise ValueError("live mode cannot use an injected transport")
    manifest, cases = runner.load_partition(manifest_path)
    if len(cases) > 12 or (live and len(cases) != 12):
        raise ValueError("At most 12 cases permitted")
    extractor_adapter.verify_binding()
    module = extractor_adapter.load_extractor()
    output_dir = Path(output_dir).resolve()
    if output_dir.is_relative_to(runner.REPO.resolve()):
        raise ValueError("Artifacts must be outside source repository")
    output_dir.mkdir(parents=True, exist_ok=False)
    artifact = dict(
        status="LIVE FREE SINGLE-PASS BASELINE" if live else "MOCK VERIFICATION ONLY",
        limitation="Single-pass baseline, not production-pipeline equivalence; human review pending",
        started_at=datetime.now(timezone.utc).isoformat(),
        endpoint=ENDPOINT,
        model=MODEL,
        case_count=len(cases),
        attempted_count=0,
        completion_count=0,
        per_case=[],
        primary_metric="weighted_field_level_accuracy",
        primary_score=None,
        declared_denominator_score=0.0,
        cost_usd=None,
        accounting_complete=True,
        stop_reason=None,
        partition_manifest_sha256=runner.digest(manifest_path),
        test_sha256=manifest["test_sha256"],
        train_dev_sha256=manifest["train_dev_sha256"],
        source_hashes=manifest["source_hashes"],
        frozen=frozen_files(manifest_path),
        command=list(sys.argv),
        max_attempts=len(cases),
        max_tokens=4096,
        retries=0,
        fallback=False,
    )
    out = output_dir / "run.json"
    runner.save(out, artifact)
    actual_transport = (
        transport
        if transport is not None
        else httpx.HTTPTransport(retries=0, trust_env=False)
    )
    with httpx.Client(
        transport=actual_transport,
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(120, connect=20),
        event_hooks={"request": [guard_request]},
    ) as client:
        try:
            catalog_response = client.get(CATALOG)
            runner.save(
                output_dir / "catalog.json",
                dict(
                    status=catalog_response.status_code,
                    body_sha256=sha(catalog_response.content),
                    data=catalog_response.json(),
                ),
            )
            if catalog_response.status_code != 200:
                raise AccountingError("Public catalog HTTP status is not 200")
            artifact["catalog_model"] = check_catalog(catalog_response.json())
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            artifact["stop_reason"] = type(exc).__name__ + ": " + str(exc)
            artifact["accounting_complete"] = False
        if not artifact["stop_reason"]:
            for index, case in enumerate(cases, 1):
                extractor_adapter.verify_binding()
                body = request_body(module, case)
                body_bytes = encoded(body)
                row = dict(
                    id=case["id"],
                    score=0.0,
                    weight=case["weight"],
                    prediction=None,
                    error=None,
                    accounting_complete=False,
                    request_body=body,
                    request_sha256=sha(body_bytes),
                    response=None,
                )
                start = time.perf_counter()
                artifact["attempted_count"] += 1
                try:
                    response = client.post(
                        ENDPOINT,
                        content=body_bytes,
                        headers={"content-type": "application/json"},
                    )
                    row["http_status"] = response.status_code
                    row["raw_response_sha256"] = sha(response.content)
                    try:
                        row["response"] = receipt(response)
                        row["filtered_response_sha256"] = sha(encoded(row["response"]))
                    except (ValueError, KeyError, TypeError, AttributeError):
                        row["response"] = None
                    if response.status_code != 200:
                        raise AccountingError("Completion HTTP status is not 200")
                    data = response.json()
                    check_response(data)
                    row["accounting_complete"] = True
                    try:
                        if data["choices"][0].get("finish_reason") != "stop":
                            raise ValueError("Completion did not finish normally")
                        content = data["choices"][0]["message"]["content"]
                        prediction = json.loads(content)
                        if not isinstance(prediction, dict):
                            raise ValueError("Completion content must be a JSON object")
                        row["raw_prediction"] = prediction
                        prediction, removed = module.injection_guard.sanitize_output(
                            prediction
                        )
                        validated = module.DOCUMENT_TYPE_MAP[
                            case["doc_type"]
                        ].model_validate(prediction)
                        prediction = validated.model_dump(mode="json")
                        row["prediction"] = prediction
                        row["prediction_sha256"] = sha(encoded(prediction))
                        row["sanitized_keys"] = removed
                        row["score"] = runner.scoring.score_extraction(
                            prediction, case["expected"], case["critical_fields"]
                        )
                        artifact["completion_count"] += 1
                    except (ValueError, TypeError, KeyError, IndexError) as exc:
                        row["error"] = type(exc).__name__ + ": " + str(exc)
                except (
                    httpx.HTTPError,
                    ValueError,
                    KeyError,
                    TypeError,
                    AttributeError,
                ) as exc:
                    row["error"] = type(exc).__name__ + ": " + str(exc)
                    artifact["stop_reason"] = row["error"]
                    artifact["accounting_complete"] = False
                row["latency_ms"] = (time.perf_counter() - start) * 1000
                runner.save(output_dir / f"attempt-{index:03d}.json", row)
                artifact["per_case"].append(row)
                runner.save(out, artifact)
                if artifact["stop_reason"]:
                    break
    artifact["declared_denominator_score"] = sum(
        row["score"] * row["weight"] for row in artifact["per_case"]
    ) / sum(case["weight"] for case in cases)
    if artifact["accounting_complete"]:
        artifact["cost_usd"] = "0"
        if artifact["attempted_count"] == len(cases) == 12:
            artifact["primary_score"] = artifact["declared_denominator_score"]
    attempted_ids = {row["id"] for row in artifact["per_case"]}
    artifact["unattempted_ids"] = [
        case["id"] for case in cases if case["id"] not in attempted_ids
    ]
    artifact["ended_at"] = datetime.now(timezone.utc).isoformat()
    runner.save(out, artifact)
    return artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--live", action="store_true", help="Permit anonymous bounded free-model run"
    )
    args = parser.parse_args()
    result = run(ROOT / "partition_manifest.json", args.output_dir, live=args.live)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "status",
                    "attempted_count",
                    "completion_count",
                    "primary_score",
                    "cost_usd",
                    "stop_reason",
                )
            }
        )
    )
    return 1 if result["stop_reason"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
