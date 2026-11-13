"""Tests for the pure helpers in scripts/bench_live.py."""
from __future__ import annotations

from scripts.bench_live import SpendGuard, llm_delta, pct, reprice


def test_pct_nearest_rank():
    assert pct([], 0.95) is None
    assert pct([300.0, 100.0, 200.0], 0.5) == 200.0
    assert pct([float(i) for i in range(1, 21)], 0.95) == 19.0


def test_llm_delta_isolates_the_run():
    before = {
        "total_calls": 2, "total_input_tokens": 100, "total_output_tokens": 10, "total_cost_usd": 0.01,
        "by_model": [{"model": "m1", "call_count": 2, "input_tokens": 100, "output_tokens": 10,
                      "estimated_cost_usd": 0.01, "avg_latency_ms": 900}],
    }
    after = {
        "total_calls": 5, "total_input_tokens": 400, "total_output_tokens": 40, "total_cost_usd": 0.05,
        "by_model": [
            {"model": "m1", "call_count": 3, "input_tokens": 250, "output_tokens": 25,
             "estimated_cost_usd": 0.03, "avg_latency_ms": 500},
            {"model": "m2", "call_count": 2, "input_tokens": 150, "output_tokens": 15,
             "estimated_cost_usd": 0.02, "avg_latency_ms": 200},
        ],
    }
    d = llm_delta(before, after)
    assert d["calls"] == 3
    assert d["input_tokens"] == 300
    assert d["cost_usd_app_price_table"] == 0.04
    assert d["by_model"]["m1"]["input_tokens"] == 150
    assert "avg_latency_ms" not in d["by_model"]["m1"]
    assert d["by_model"]["m2"]["call_count"] == 2


def test_reprice_uses_list_prices_and_flags_unknown_claude_models():
    usd, unpriced = reprice({
        "claude-haiku-4-5-20251001": {"input_tokens": 1_000_000, "output_tokens": 100_000},
        "claude-sonnet-4-6": {"input_tokens": 100_000, "output_tokens": 10_000},
        "gemini-embedding-2-preview": {"input_tokens": 5_000_000, "output_tokens": 0},
    })
    assert usd == round(1.00 + 0.50 + 0.30 + 0.15, 6)
    assert unpriced == []

    _, unpriced = reprice({"claude-opus-9": {"input_tokens": 1, "output_tokens": 1}})
    assert unpriced == ["claude-opus-9"]


def test_spend_guard_stops_before_the_next_document_could_pass_the_cap():
    g = SpendGuard(max_usd=1.00)
    g.record(0.30)
    assert g.stop_reason() is None
    g.record(0.65)  # dearest document so far: 0.35
    assert g.stop_reason() is None  # 0.65 + 0.35 == 1.00, not over
    g.record(0.70)
    assert g.stop_reason() is not None  # 0.70 + 0.35 > 1.00
    g = SpendGuard(max_usd=0.50)
    g.record(0.60)
    assert "at or over" in g.stop_reason()


def _fake_deployment(tokens_per_doc: tuple[int, int], traces: bool = True):
    """httpx transport for a deployment where each upload adds Sonnet tokens."""
    import httpx

    state = {"docs": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/health":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/api/v1/documents/upload":
            state["docs"] += 1
            return httpx.Response(202, json={"job_id": f"j{state['docs']}"})
        if path.startswith("/api/v1/jobs/"):
            return httpx.Response(200, json={"status": "completed", "processing_time_ms": 900})
        if path == "/api/v1/metrics/llm":
            n = state["docs"] if traces else 0
            inp, out = n * tokens_per_doc[0], n * tokens_per_doc[1]
            models = [{"model": "claude-sonnet-4-6", "call_count": 2 * n, "input_tokens": inp,
                       "output_tokens": out, "estimated_cost_usd": 0.0}] if n else []
            return httpx.Response(200, json={"total_calls": 2 * n, "total_input_tokens": inp,
                                             "total_output_tokens": out, "total_cost_usd": 0.0,
                                             "by_model": models})
        return httpx.Response(404)

    return httpx.MockTransport(handler), state


def _run_main(monkeypatch, tmp_path, transport, *extra):
    import sys

    import httpx

    import scripts.bench_live as bl

    real_client = httpx.Client
    monkeypatch.setattr(bl.httpx, "Client", lambda **kw: real_client(transport=transport, **kw))
    monkeypatch.setattr(bl.time, "sleep", lambda s: None)
    monkeypatch.setenv("DOCEXTRACT_API_KEY", "test")
    sample = tmp_path / "doc.pdf"
    sample.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(sys, "argv", ["bench_live.py", "--base-url", "http://x", "--files", str(sample),
                                      "--out", str(tmp_path / "out.json"), *extra])
    return bl.main()


def test_main_stops_before_the_cap(monkeypatch, tmp_path):
    import json

    # 10k in + 2k out of Sonnet = $0.06 a document; a $0.20 cap allows 3
    transport, state = _fake_deployment((10_000, 2_000))
    code = _run_main(monkeypatch, tmp_path, transport, "--runs", "10", "--max-llm-usd", "0.20")
    assert code == 3
    assert state["docs"] == 3
    out = json.loads((tmp_path / "out.json").read_text())
    assert out["stopped_early"] and out["llm_cost_usd_list_price"] <= 0.20


def test_main_refuses_runs_over_max_docs(monkeypatch, tmp_path):
    transport, state = _fake_deployment((1, 1))
    assert _run_main(monkeypatch, tmp_path, transport, "--runs", "50", "--max-docs", "40") == 2
    assert state["docs"] == 0


def test_main_stops_when_spend_is_invisible(monkeypatch, tmp_path):
    transport, state = _fake_deployment((1, 1), traces=False)
    assert _run_main(monkeypatch, tmp_path, transport, "--runs", "5") == 3
    assert state["docs"] == 1


def test_main_finishes_under_the_cap(monkeypatch, tmp_path):
    transport, state = _fake_deployment((1_000, 100))
    assert _run_main(monkeypatch, tmp_path, transport, "--runs", "4") == 0
    assert state["docs"] == 4
