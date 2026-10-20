"""Network-denied contract tests with independent synthetic miniature fixtures."""

import hashlib
import json
import socket
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

try:
    import free_baseline as baseline
except ModuleNotFoundError:
    baseline = None


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Unit tests must never open sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)


def test_implementation_available():
    assert baseline is not None, "Free baseline implementation is missing"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    assert baseline is not None, "Free baseline implementation is missing"

    class Schema(BaseModel):
        total: float

    guard = SimpleNamespace(
        DEFENSE_SYSTEM_CLAUSE="DEFEND",
        wrap_untrusted=lambda text: "<untrusted>" + text + "</untrusted>",
        sanitize_output=lambda data: (
            {k: v for k, v in data.items() if k != "secret"},
            [],
        ),
    )
    module = SimpleNamespace(
        prompt_config=SimpleNamespace(
            extract_system_prompt="Extract.",
            extract_prompt="Type {doc_type}: {text}",
            params=SimpleNamespace(extract_text_limit=20),
        ),
        injection_guard=guard,
        DOCUMENT_TYPE_MAP={d: Schema for d in ("invoice", "receipt", "purchase_order")},
    )
    monkeypatch.setattr(baseline.extractor_adapter, "verify_binding", lambda: None)
    monkeypatch.setattr(baseline.extractor_adapter, "load_extractor", lambda: module)
    cases = [
        dict(
            id=f"case-{i}",
            weight=1,
            expected={"total": 11},
            critical_fields=["total"],
            input_text="Document total 11",
            doc_type=d,
        )
        for i, d in enumerate(["invoice", "receipt", "purchase_order"] * 4)
    ]
    test = tmp_path / "test.json"
    train = tmp_path / "train.json"
    test.write_text(json.dumps(cases))
    train.write_text("[]")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            dict(
                test_path="test.json",
                train_dev_path="train.json",
                test_sha256=hashlib.sha256(test.read_bytes()).hexdigest(),
                train_dev_sha256=hashlib.sha256(train.read_bytes()).hexdigest(),
                source_hashes={},
                test_case_count=12,
            )
        )
    )
    return manifest, tmp_path / "run"


def catalog():
    return {
        "data": [
            {
                "id": "nvidia/nemotron-3-ultra-550b-a55b:free",
                "isFree": True,
                "pricing": {"prompt": "0", "completion": "0"},
            }
        ]
    }


def response():
    return dict(
        id="completion",
        provider="test",
        model="nvidia/nemotron-3-ultra-550b-a55b:free",
        usage=dict(prompt_tokens=30, completion_tokens=10, cost=0, is_byok=False),
        choices=[
            dict(
                finish_reason="stop",
                message=dict(
                    content='{"total":11,"secret":"strip"}',
                    reasoning="DO NOT PERSIST",
                    reasoning_details=[{"text": "DO NOT PERSIST"}],
                ),
            )
        ],
    )


def execute(setup, handler, **kwargs):
    manifest, output = setup
    return baseline.run(
        manifest, output, transport=httpx.MockTransport(handler), **kwargs
    )


def test_success_all_doctypes_no_label_leak_or_auth(setup):
    requests = []

    def handler(req):
        assert not req.headers.get("authorization") and not req.headers.get("cookie")
        if req.method == "GET":
            return httpx.Response(200, json=catalog())
        body = json.loads(req.content)
        assert body["max_tokens"] == 4096 and body["temperature"] == 0
        assert body["stream"] is False
        assert (
            "expected" not in req.content.decode()
            and "critical_fields" not in req.content.decode()
        )
        requests.append(body)
        return httpx.Response(200, json=response())

    result = execute(setup, handler)
    assert result["primary_score"] == 1.0
    assert result["attempted_count"] == result["completion_count"] == 12
    assert result["cost_usd"] == "0"
    assert {x["messages"][1]["content"].split(":")[0] for x in requests} == {
        "Type invoice",
        "Type receipt",
        "Type purchase_order",
    }
    assert result["per_case"][0]["prediction"] == {"total": 11.0}
    traces = list(setup[1].glob("attempt-*.json"))
    assert len(traces) == 12 and all(
        "DO NOT PERSIST" not in p.read_text() for p in traces
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "paid",
        "missing_cost",
        "cost",
        "identity",
        "usage",
        "byok",
        "cost_details",
        "http",
    ],
)
def test_accounting_failure_stops_and_retains_denominator(setup, mutation):
    calls = []

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json=catalog())
        calls.append(req)
        data = response()
        if mutation == "paid":
            data["model"] = "paid-model"
        if mutation == "identity":
            data["model"] += "-other"
        if mutation == "missing_cost":
            del data["usage"]["cost"]
        if mutation == "cost":
            data["usage"]["cost"] = 0.01
        if mutation == "usage":
            data["usage"]["prompt_tokens"] = True
        if mutation == "byok":
            data["usage"]["is_byok"] = True
        if mutation == "cost_details":
            data["usage"]["cost_details"] = {"upstream_inference_cost": "0.01"}
        return httpx.Response(403 if mutation == "http" else 200, json=data)

    result = execute(setup, handler)
    assert len(calls) == 1
    assert result["attempted_count"] == 1 and result["case_count"] == 12
    assert result["primary_score"] is None and result["stop_reason"]
    assert result["cost_usd"] is None
    assert result["per_case"][0]["score"] == 0
    assert (setup[1] / "attempt-001.json").exists()


@pytest.mark.parametrize("content", ["not json", '{"total":"bad"}', "[]", "{}"])
def test_content_errors_score_zero_without_retry(setup, content):
    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json=catalog())
        data = response()
        data["choices"][0]["message"]["content"] = content
        return httpx.Response(200, json=data)

    result = execute(setup, handler)
    assert result["attempted_count"] == 12
    assert result["completion_count"] == 0 and result["primary_score"] == 0
    assert all(row["score"] == 0 and row["error"] for row in result["per_case"])


@pytest.mark.parametrize("mutation", ["paid", "missing", "absent", "invalid"])
def test_catalog_failure_never_sends_cases(setup, mutation):
    calls = []

    def handler(req):
        calls.append(req.method)
        data = catalog()
        if mutation == "paid":
            data["data"][0]["pricing"]["prompt"] = "0.01"
        if mutation == "missing":
            del data["data"][0]["isFree"]
        if mutation == "absent":
            data["data"] = []
        if mutation == "invalid":
            data["data"][0]["pricing"]["prompt"] = "NaN"
        return httpx.Response(200, json=data)

    result = execute(setup, handler)
    assert calls == ["GET"] and result["attempted_count"] == 0
    assert result["primary_score"] is None and result["stop_reason"]


def test_network_failure_saved_without_retry(setup):
    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json=catalog())
        raise httpx.ConnectError("offline", request=req)

    result = execute(setup, handler)
    assert result["attempted_count"] == 1 and result["primary_score"] is None
    assert result["per_case"][0]["error"] and (setup[1] / "attempt-001.json").exists()


def test_no_overwrite(setup):
    setup[1].mkdir()
    with pytest.raises(FileExistsError):
        execute(setup, lambda req: None)


def test_default_refuses_network_and_custom_transport(setup):
    with pytest.raises(ValueError, match="live"):
        baseline.run(*setup)
    with pytest.raises(ValueError, match="MockTransport"):
        baseline.run(*setup, transport=httpx.HTTPTransport())


def test_truncated_content_cannot_count_as_valid_completion(setup):
    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json=catalog())
        data = response()
        data["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=data)

    result = execute(setup, handler)
    assert result["completion_count"] == 0
    assert result["attempted_count"] == 12
    assert result["primary_score"] == 0


def test_provider_cookies_never_forwarded_to_later_requests(setup):
    def handler(req):
        assert "cookie" not in req.headers
        if req.method == "GET":
            return httpx.Response(
                200, json=catalog(), headers={"set-cookie": "catalog=blocked; Path=/"}
            )
        return httpx.Response(
            200, json=response(), headers={"set-cookie": "completion=blocked; Path=/"}
        )

    result = execute(setup, handler)
    assert result["attempted_count"] == 12 and result["completion_count"] == 12
