# DocExtract AI

Fixture-backed document intelligence with two-pass extraction, agentic retrieval, and an eval gate.

<p align="center">
  <img src="./docs/assets/eval-proof.svg" width="720" alt="DocExtract deterministic evaluation proof: 95.5% field-level score from a 28-fixture replay, two extraction passes, an eval gate, and a separately labeled 202-case authoring corpus." />
</p>

## Deterministic eval replay

> **95.5% field-level score from a deterministic 28-fixture replay**

| Evidence | What it is | What it is not |
|----------|------------|----------------|
| **28 fixtures** | Deterministic replay behind the 95.5% field-level score (`scripts/eval_offline_replay.py`, `autoresearch/baseline.json`) | Not the authoring-corpus size |
| **202 cases** | Authoring corpus (151 golden + 51 adversarial) | Not the replay fixture total and not the score population |

How the 28-fixture replay is scored, and how it relates to the 202-case authoring corpus: [docs/eval-boundary.md](docs/eval-boundary.md). Held-out live eval (protocol only; performance unmeasured): [docs/held-out-live-eval-protocol.md](docs/held-out-live-eval-protocol.md).

### Reviewer path

1. Replay the committed fixtures: `python scripts/eval_offline_replay.py --floor 0.85`
2. Compare the replayed field-level score to **95.5%**
3. Inspect the two extraction passes and the deterministic eval gate on the proof card
4. Continue to retrieval, architecture, and the honest scope notes below
5. Run the local fixture-backed UI: `DEMO_MODE=true streamlit run frontend/app.py` — [DEMO.md](DEMO.md)

[![Tests](https://github.com/ChunkyTortoise/docextract/actions/workflows/ci.yml/badge.svg)](https://github.com/ChunkyTortoise/docextract/actions/workflows/ci.yml)
[![Eval Gate](https://github.com/ChunkyTortoise/docextract/actions/workflows/eval-gate.yml/badge.svg)](https://github.com/ChunkyTortoise/docextract/actions/workflows/eval-gate.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)

The hosted Streamlit URL is intentionally omitted until anonymous access is verified. Static preview and trace visualizer live in [`site/`](site/) and [`frontend/pages/agent_trace.py`](frontend/pages/agent_trace.py).

## Eval gate {#eval-gate}

Prompts are code. DocExtract treats extraction quality as a **merge-blocking CI signal**, not a post-hoc dashboard number.

| Signal | What runs | When |
|--------|-----------|------|
| **Offline replay** (badge driver) | `scripts/eval_offline_replay.py` on 28 committed fixtures | Every eval-gated PR; zero API cost |
| **Variance-calibrated gate** | `scripts/eval_gate.py` vs `autoresearch/baseline.json` | PRs touching prompts / extraction services |
| **Paid live eval** | Promptfoo, RAGAS, LLM-judge | Only when `ANTHROPIC_API_KEY` is present in CI; skipped otherwise |
| **Held-out live protocol** | Public or synthetic docs, untouched test partition, `score_extraction` | Unmeasured until a funded run is logged ([protocol](docs/held-out-live-eval-protocol.md)) |
| **Drift cron** | Golden set vs production prompt version | Daily 13:23 UTC |

**Eval gate proof (red blocked PR):** [#32 — intentional regression (keep open / expect red)](https://github.com/ChunkyTortoise/docextract/pull/32). Executed vs replayed stages: [docs/eval-gate-proof.md](docs/eval-gate-proof.md). See also [docs/eval-methodology.md](docs/eval-methodology.md).

| Metric | Value | Basis |
|--------|-------|-------|
| Extraction accuracy (field-level, critical fields weighted 2×) | **95.5%** | Always-on CI offline replay of **28** deterministic fixtures (`scripts/eval_offline_replay.py`); not a paid live grade |
| Test suite | **80% CI coverage gate** | `--cov-fail-under=80`; the changing collected-test total is intentionally omitted ([portfolio-metrics.yaml](docs/portfolio-metrics.yaml)) |
| Authoring corpus | **202 cases** (151 golden + 51 adversarial) | `evals/golden_set.jsonl` + `evals/adversarial_set.jsonl` (line counts); separate from the 28-fixture offline replay |
| Cost / latency | See [cost-model.md](docs/cost-model.md) | Modeled only until a funded `scripts/benchmark.py` run is committed |

<details>
<summary>CI-replayed eval breakdown by document type (from committed <code>autoresearch/baseline.json</code>)</summary>

| Document type | Score | Cases |
|---|---|---|
| invoice | 0.9731 | 13 |
| receipt | 0.9107 | 4 |
| purchase_order | 0.9762 | 3 |
| bank_statement | 0.9581 | 4 |
| medical_record | 0.9923 | 3 |
| identity_document | 0.8139 | 1 |

Overall: 0.955 across 28 cases, replayed on every eval-gated PR at zero API cost.

</details>

More: [CASE_STUDY.md](CASE_STUDY.md) · [docs/eval-methodology.md](docs/eval-methodology.md) · [docs/eval-boundary.md](docs/eval-boundary.md) · [docs/held-out-live-eval-protocol.md](docs/held-out-live-eval-protocol.md) · [evals/](evals/)

![DocExtract AI fixture-backed demo with evaluation scores, agent trace, and cost analysis](docs/screenshots/demo-hero.png)

## What this does

FastAPI document intelligence: upload PDFs and images, classify with cost-aware routing, extract structured fields via a **two-pass Claude pipeline**, embed into **pgvector**, and query with **agentic RAG** (ReAct loop with streaming SSE reasoning).

```
Upload → ARQ worker → classify → extract → validate → embed → search / agentic RAG
         ↑
    Optional trace exporters        Offline eval replay (CI only, not on request path)
```

## Why this is interesting (engineering)

- **Eval-gated CI**: `eval-gate.yml` offline job replays 28-case deterministic baseline at zero API cost; PRs touching prompts or extraction services must pass before merge
- **FastAPI & Strict Type Safety**: End-to-end Pydantic V2 validation contracts, typed error domains, and deterministic schema enforcement preventing malformed extraction persistence
- **PostgreSQL (pgvector) & ARQ Queue**: Document chunk embeddings indexed via pgvector HNSW vectors, decoupled background document processing via Redis and ARQ worker queue
- **Agentic RAG**: ReAct Think → Act → Observe over hybrid retrieval tools; primary search story in API and Streamlit ([`agentic_rag.py`](app/services/agentic_rag.py), [`agent_trace.py`](frontend/pages/agent_trace.py))
- **Cost-aware model routing**: Haiku for classification, Sonnet for extraction; prompt caching on system prompts; circuit breaker with Haiku fallback
- **Independent judge**: Gemini grades extractions to reduce self-grading bias ([ADR-0018](docs/adr/0018-independent-judge-and-multi-provider-router.md))
- **Optional observability**: Langfuse integration, LangSmith, and OpenTelemetry exporters are available when configured ([`app/observability.py`](app/observability.py))
- **Prompt-injection defense**: runtime fence + scan + output sanitization ([ADR-0020](docs/adr/0020-indirect-prompt-injection-defense.md))

## Architecture

```mermaid
graph LR
  A[Client / Streamlit] -->|POST /documents| B[FastAPI]
  B -->|enqueue| C[ARQ Worker]
  C -->|classify + extract| D{Model Router}
  D -->|primary| E[Claude Sonnet]
  D -->|fallback| F[Claude Haiku]
  E --> G[(pgvector)]
  G -->|search| H[Agentic RAG]
  H --> A
  C -->|Langfuse| I[Traces]
  B -->|SSE /jobs/events| A
```

## Demo

Run the fixture-backed demo locally with no API key:

```bash
DEMO_MODE=true streamlit run frontend/app.py
```

Progress streams over SSE: `/jobs/{id}/events` (extraction stages) and `/agent-search/stream` (agentic retrieval reasoning).

## Install

```bash
git clone https://github.com/ChunkyTortoise/docextract.git
cd docextract
cp .env.example .env  # Add ANTHROPIC_API_KEY + GEMINI_API_KEY
docker compose up -d
open http://localhost:8501  # Streamlit UI
```

Services: API `:8000` (`/docs` for Swagger) | Frontend `:8501` | PostgreSQL `:5432` | Redis `:6379`

## Tests

```bash
pytest tests/ --collect-only -q       # Discover the current suite; count is not a portfolio claim
python scripts/eval_offline_replay.py --floor 0.85   # Always-on CI offline replay (badge driver)
python scripts/run_eval_ci.py --ci                    # Wrapper; same 28-case deterministic path
make eval                             # Optional paid live eval; requires configured credentials
```

## Architecture Decisions

20 ADRs at [docs/adr/](docs/adr/). Key decisions:

| ADR | Decision |
|-----|----------|
| [ADR-0003](docs/adr/0003-two-pass-extraction.md) | Two-pass Claude extraction with confidence gating |
| [ADR-0006](docs/adr/0006-circuit-breaker-model-fallback.md) | Circuit breaker model fallback chain |
| [ADR-0015](docs/adr/0015-prompt-caching.md) | Anthropic prompt caching for eval cost reduction |
| [ADR-0018](docs/adr/0018-independent-judge-and-multi-provider-router.md) | Gemini as independent judge |
| [ADR-0019](docs/adr/0019-reranker-and-agentic-reflection.md) | TF-IDF reranker + agentic self-reflection loop |

**Scope notes (honest):** GraphRAG hybrid retrieval is opt-in (`GRAPH_RETRIEVAL_ENABLED=false` by default): regex entity graph, file-backed. Semantic cache ([ADR-0017](docs/adr/0017-semantic-cache-l1-l2.md)) is implemented but feature-flagged off and not wired into the extraction hot path. Langfuse, LangSmith, and OpenTelemetry integrations require configuration and are not presented as verified live telemetry.

More: [DEMO.md](DEMO.md) | [docs/cost-model.md](docs/cost-model.md) | [site/](site/)

## License

MIT
