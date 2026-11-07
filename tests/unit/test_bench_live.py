"""Tests for the pure helpers in scripts/bench_live.py."""
from __future__ import annotations

from scripts.bench_live import llm_delta, pct


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
