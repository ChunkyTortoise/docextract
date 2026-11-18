# DocExtract: document extraction with an eval gate in CI

DocExtract is a FastAPI service that turns invoices, receipts, statements and other PDFs or scans into validated structured records, using a two-pass Claude extraction pipeline, pgvector, and agentic RAG for questions over stored documents.

On a deterministic replay of 28 committed extraction outputs it scores 0.9555 weighted field-level accuracy, and 474 of 482 extracted values (98.3%) are found in the source text. CI fails any pull request that touches prompts or the extractor if the replay drops below 0.85 or more than 0.03 under baseline ([recorded failing run](https://github.com/ChunkyTortoise/docextract/actions/runs/29670515963/job/88148512559)). The replay scores frozen predictions, so a prompt or model change still needs the paid live eval.

Reproduce the headline number with no install and no API key (Python 3.12, standard library only):

```bash
python3 scripts/eval_offline_replay.py --floor 0.85
```

[![CI](https://github.com/ChunkyTortoise/docextract/actions/workflows/ci.yml/badge.svg)](https://github.com/ChunkyTortoise/docextract/actions/workflows/ci.yml)
[![Eval Gate](https://github.com/ChunkyTortoise/docextract/actions/workflows/eval-gate.yml/badge.svg)](https://github.com/ChunkyTortoise/docextract/actions/workflows/eval-gate.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

<p align="center">
  <img src="./docs/screenshots/demo-hero.png" width="720" alt="DocExtract fixture explorer showing stored invoice fields, sample values, and explicitly labeled sample confidence." />
</p>
<p align="center"><sub>Fixture explorer, runnable with no API key (<a href="#explore-stored-extractions-in-the-ui">UI explorer</a>). <a href="docs/screenshots/fixture-walkthrough.gif">9-second walkthrough</a> · <a href="docs/screenshots/demo-mobile.png">mobile view</a> · <a href="docs/screenshots/PROVENANCE.md">capture provenance</a></sub></p>

## Results

Every number below comes from a committed artifact and a command that needs no API key. "Model" is the model that produced the frozen predictions; the scorers themselves are deterministic and call no model.

| Metric | Value | n | Dataset | Date | Model | Baseline | Reproduce |
|---|---|---|---|---|---|---|---|
| Weighted field-level extraction score (critical fields 2x, partial credit for near matches; not F1) | **0.9555** | 28 fixtures (of 72 lookup cases) | [`autoresearch/golden_responses/`](autoresearch/golden_responses/) scored against [`eval_dataset_72.json`](autoresearch/eval_dataset_72.json) | rerun 2026-11-17 | claude-sonnet-4-6 (frozen) | 0.95546 in [`baseline.json`](autoresearch/baseline.json); CI floor 0.85, max drop 0.03 | `python3 scripts/eval_offline_replay.py --floor 0.85` |
| Extracted values found in the source text (faithfulness) | **0.9834** (8 unsupported) | 482 values, 28 cases | same 28 fixtures | rerun 2026-11-17 | claude-sonnet-4-6 (frozen) | gate: hallucination rate at most 0.05 | `python3 scripts/eval_hallucination.py` |
| Planted hallucinations caught by the grounding scorer | **46/46** | 46 planted values | self-test inside the same script | rerun 2026-11-17 | none (synthetic) | none | `python3 scripts/eval_hallucination.py` |
| Tests on a fresh clone, no API key | **1632 passed, 27 skipped** | full `tests/` tree, 2 e2e deselected | repository tests | 2026-11-17 | none | CI coverage floor 80% ([`ci.yml`](.github/workflows/ci.yml)) | see [Run the tests](#run-the-tests) |

Per-document-type replay scores, the eval corpus inventory (200 authoring cases, 20 ADRs) and what each number does not cover are in [How it's evaluated](#how-its-evaluated) and [Methodology & limits](#methodology--limits).

[Engineering evidence](docs/reliability-evidence.md): observed queue and database failures, repairs, test receipts and reproduction boundaries.

[Historical single-pass extraction diagnostic](docs/evidence/2026-10-08-free-baseline/README.md): saved outputs and offline verification for 12 frozen synthetic text cases using Nemotron at source `09a690b`. The reference-field score does not assess every output field. Human review found three subtotal mappings that conflict with the accepted draft-only policy; all other saved fields were accepted. This is separate from the production extraction pipeline.

## Quickstart (no API key)

From a fresh clone, three commands reproduce both scored rows of the Results table. They need Python 3.12 and nothing else installed:

```bash
git clone https://github.com/ChunkyTortoise/docextract.git && cd docextract
python3 scripts/eval_offline_replay.py --floor 0.85
python3 scripts/eval_hallucination.py
```

The first script ends with a `PASS: replayed 28/72 corpus cases` line reporting combined field accuracy 0.9555, and the second with `PASS: hallucination rate 0.0166 <= 0.05; self-test 46/46`. Both write JSON to `eval_artifacts/`. To browse the same fixtures field by field, run `streamlit run space_app.py` after installing `requirements_demo.txt` (below); [docs/deploy-hf-space.md](docs/deploy-hf-space.md) has the steps to host it.

### Explore stored extractions in the UI

```bash
python3 -m venv .venv-demo
.venv-demo/bin/python -m pip install -r requirements_demo.txt
.venv-demo/bin/python -m streamlit run streamlit_demo.py
```

The explorer reads committed JSON samples from `frontend/demo_data/` and makes no model or database calls. It uses a separate demo environment so Streamlit dependencies don't mix with the backend stack. On Windows, use `.venv-demo\Scripts\python`. The Fields / Search / Trace / Eval / Cost walkthrough is in [DEMO.md](DEMO.md).

### Run the full stack (needs API keys)

```bash
cp .env.example .env  # add ANTHROPIC_API_KEY and GEMINI_API_KEY
docker compose up -d
open http://localhost:8501  # Streamlit UI
```

Services: API `:8000` (`/docs` for Swagger) · Frontend `:8501` · PostgreSQL `:5432` · Redis `:6379`.

## How it works

```mermaid
flowchart LR
  UI["Streamlit UI or API client"] -->|"POST /api/v1/documents/upload"| API["FastAPI"]
  API -->|"enqueue"| Q[("Redis + ARQ")]
  Q --> ING
  subgraph W["ARQ worker"]
    ING["Ingest: PDF text or OCR"] --> CLS["Classify: Haiku, Sonnet fallback"]
    CLS --> EXT["Two-pass extract: Sonnet, Haiku fallback, injection guard"]
    EXT --> VAL["Validate"]
    VAL --> EMB["Embed: Gemini"]
    EMB --> STO["Store record and embedding"]
  end
  STO --> DB[("Postgres + pgvector HNSW")]
  W -.->|"stage events via Redis pub/sub"| API
  API -->|"SSE job events"| UI
  UI -->|"POST /api/v1/agent-search/stream"| RAG["Agentic RAG: ReAct over vector, BM25, hybrid tools"]
  RAG --> DB
  STO -.->|"about 1 in 10 jobs"| J["LLM judge: Gemini, Haiku fallback, off by default"]
  W -.->|"model calls"| T[("llm_traces: tokens, latency")]
  RAG -.->|"model calls"| T
  T --> M["GET /api/v1/metrics/llm"]
  subgraph CI["CI only, not on the request path"]
    R["Offline replay: 28 committed fixtures"] --> G{"score floor"}
  end
```

- **Two-pass extraction:** pass 1 extracts fields and a confidence score; a correction pass runs only when confidence falls below a per-document-type threshold ([ADR-0003](docs/adr/0003-two-pass-extraction.md)). Pydantic v2 schemas reject malformed output before it is stored.
- **Cost-aware routing:** Haiku classifies and Sonnet extracts, with prompt caching on system prompts and a circuit breaker that falls back to Haiku ([ADR-0006](docs/adr/0006-circuit-breaker-model-fallback.md), [ADR-0015](docs/adr/0015-prompt-caching.md)).
- **Agentic RAG:** a ReAct loop (think, act, observe) over vector, BM25 and hybrid retrieval tools, with reasoning streamed over SSE ([`agentic_rag.py`](app/services/agentic_rag.py), [`agent_trace.py`](frontend/pages/agent_trace.py)).
- **Prompt-injection defense:** both extraction paths fence untrusted document text and strip exfiltration keys from the output; the vision path also runs a heuristic pattern scan. This is a first layer, not a proof of safety; known gaps are listed under [Decisions, failures, limits](#decisions-failures-limits) ([ADR-0020](docs/adr/0020-indirect-prompt-injection-defense.md)).
- **Async pipeline:** an ARQ worker on Redis does the processing; pgvector HNSW stores the embeddings ([ADR-0001](docs/adr/0001-arq-over-celery.md), [ADR-0002](docs/adr/0002-pgvector-over-dedicated-vector-db.md)).
- **Versioned prompts and PII redaction in traces:** [prompt registry](app/services/prompt_registry.py) and [`pii_sanitizer.py`](app/services/pii_sanitizer.py).

Deployment artifacts: [AWS ECS Terraform](deploy/aws-ecs/), [Kubernetes manifests](deploy/) and [Grafana configuration](deploy/grafana/).

## How it's evaluated

| Signal | What runs | When |
|--------|-----------|------|
| **Offline replay** (badge driver) | `scripts/eval_offline_replay.py` on 28 committed fixtures, against the floor in [Results](#results) | Every eval-relevant PR, pushes to `main`, and a daily drift run; zero API cost |
| **Live-eval threshold gate** | `scripts/eval_gate.py`: Promptfoo, Ragas and LLM-judge outputs vs thresholds and `autoresearch/baseline.json` | Inside the paid live job when `ANTHROPIC_API_KEY` is configured in CI |
| **CI LLM judge** | `scripts/eval_llm_judge.py` grades the golden and adversarial sets. CI calls it without `--provider` and without a Gemini key, so the script default (Gemini) falls back to Anthropic, Claude Haiku; `--provider openai` or `gemini` is available | Paid live job only |
| **In-app judge** | Gemini 2.5 Flash, with Claude Haiku fallback, grades a sample of extractions to reduce self-grading bias ([ADR-0018](docs/adr/0018-independent-judge-and-multi-provider-router.md)) | Runtime, about 1 in 10 jobs when enabled; off by default |
| **Held-out live protocol** | Public or synthetic docs, untouched test partition, `score_extraction` | [Protocol](docs/held-out-live-eval-protocol.md) ready for a funded run |

To see the gate catch a regression, read [docs/eval-gate-proof.md](docs/eval-gate-proof.md): a demo branch corrupted eight fixtures, and the [recorded Offline replay job](https://github.com/ChunkyTortoise/docextract/actions/runs/29670515963/job/88148512559) failed below the floor. The proof note keeps the log excerpt and the commands to reproduce it.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/eval/replay-by-doc-type-dark.svg">
    <img src="docs/assets/eval/replay-by-doc-type-light.svg" width="720" alt="Dot chart of weighted field-level accuracy per document type from the 28-fixture offline replay, with the case count on each row and the 0.85 CI floor marked.">
  </picture>
</p>

The chart is generated from the replay output by `python scripts/render_eval_chart.py`, and `tests/unit/test_render_eval_chart.py` fails if it drifts from the committed fixtures.

<details>
<summary>Replay score by document type (weighted field-level score)</summary>

| Document type | Score | Replayed fixtures |
|---|---|---|
| invoice | 0.9669 | 13 |
| receipt | 0.9091 | 4 |
| purchase_order | 0.9745 | 3 |
| bank_statement | 0.9613 | 4 |
| medical_record | 0.9923 | 3 |
| identity_document | 0.8139 | 1 |

The overall score across all 28 fixtures is the Results figure. Recorded 2026-09-19 (RA11).

</details>

### Run the tests

Zero API cost; PostgreSQL and Redis integration tests skip when those services are absent:

```bash
uv venv && uv pip install -e .
.venv/bin/python -m pytest tests/ -m "not e2e" --no-cov -q
make eval                                # optional paid live eval; needs credentials
```

More: [docs/eval-methodology.md](docs/eval-methodology.md) · [docs/eval-boundary.md](docs/eval-boundary.md) · [evals/](evals/) · [CASE_STUDY.md](CASE_STUDY.md)

## Design decisions

The ADRs live in [docs/adr/](docs/adr/). The key ones:

| ADR | Decision |
|-----|----------|
| [ADR-0003](docs/adr/0003-two-pass-extraction.md) | Two-pass Claude extraction with confidence gating |
| [ADR-0006](docs/adr/0006-circuit-breaker-model-fallback.md) | Circuit breaker model fallback chain |
| [ADR-0015](docs/adr/0015-prompt-caching.md) | Anthropic prompt caching for eval cost reduction |
| [ADR-0018](docs/adr/0018-independent-judge-and-multi-provider-router.md) | Gemini as independent judge |
| [ADR-0019](docs/adr/0019-reranker-and-agentic-reflection.md) | TF-IDF reranker + agentic self-reflection loop |
| [ADR-0020](docs/adr/0020-indirect-prompt-injection-defense.md) | Indirect prompt-injection defense on text and vision paths |

## Decisions, failures, limits

**Decisions**
- The pull-request gate replays frozen predictions instead of calling a model. It is deterministic and costs nothing, so it can run on every eval-relevant PR and daily. The price is that it cannot see prompt or model drift; that needs the paid live job ([eval-boundary.md](docs/eval-boundary.md)).
- Two-pass extraction with a confidence gate: the correction pass runs only below 0.80 confidence (0.90 for identity documents, `app/config.py`), so most documents pay for one model call ([ADR-0003](docs/adr/0003-two-pass-extraction.md)).
- The in-app judge uses a different provider (Gemini) from the extractor (Claude) to reduce self-grading bias, and is off by default to keep cost at zero unless enabled ([ADR-0018](docs/adr/0018-independent-judge-and-multi-provider-router.md)).
- The ReAct agent is bounded: at most 3 iterations (`app/services/agentic_rag.py:131`) and a per-request spend ceiling checked between steps, which returns a degraded answer instead of continuing.
- ARQ on Redis instead of Celery for the async worker, and pgvector inside the existing PostgreSQL instead of a separate vector database ([ADR-0001](docs/adr/0001-arq-over-celery.md), [ADR-0002](docs/adr/0002-pgvector-over-dedicated-vector-db.md)).

**Known failures, found and fixed**
- The gate does fail: a demo branch corrupted eight fixtures and the Offline replay job failed below the 0.85 floor ([eval-gate-proof.md](docs/eval-gate-proof.md)).
- The MCP fetch tool's URL guard accepted `https://localhost/`, `https://127.1/`, `https://0x7f.1/` and `https://metadata.google.internal/`. It now resolves hostnames and rejects private, loopback, link-local and short-form addresses, with tests in [`tests/unit/test_mcp_ssrf.py`](tests/unit/test_mcp_ssrf.py). DNS rebinding between the check and the fetch is still open (`mcp_server.py`).
- `pyproject.toml` pinned `starlette<0.42` while CI and Streamlit need 0.47, so a fresh `uv pip install -e .` failed at test collection in `tests/frontend`. The pin now matches `requirements_ci.txt`.
- Queue and database failures seen during development, and their repairs, are in [reliability-evidence.md](docs/reliability-evidence.md).

**Known limits, not fixed**
- The prompt-injection scan is a regex first layer. It misses paraphrases such as "Ignore the instructions above", "disregard earlier guidance" and "Ign0re previous instructions", and flags benign contract text such as "shall act as an independent contractor". The output sanitizer strips exfiltration keys only, so leaked text inside a normal field value passes. The text extraction path fences and sanitizes but does not run the scan. No attack success rate is measured, and the 11 `prompt_injection` cases in `evals/adversarial_set.jsonl` are not scored against the guard.
- If the Gemini embedding call fails, the job fails at the embed step and follows the ARQ retry policy (`worker/tasks.py`); there is no extract-without-search fallback.
- 44 of the 72 lookup cases have no recorded prediction, so the replay covers 28. Retrieval recall, answer faithfulness, agent tool choice and held-out live accuracy are unmeasured; cost and latency are modeled, not metered ([Roadmap](#roadmap)).
- The 8 unsupported values from the grounding run are categorized in [error-taxonomy.md](docs/error-taxonomy.md): 4 from one merged line item, 2 wrong numbers, 1 brand-to-generic drug name swap, 1 paraphrase. Failure modes the eval set is built around (OCR noise, ambiguous dates, missing totals, non-USD currency) are listed in [eval-failure-analysis.md](docs/eval-failure-analysis.md).

## Methodology & limits

<details>
<summary>What each number covers, and what is not measured yet</summary>

**Extraction score**
- The Results score is a weighted field-level score (critical fields count 2×) from a deterministic replay of 28 committed prediction fixtures. It gives partial credit: strings by normalized Levenshtein similarity, numbers that match within one percent, and half credit when a value is extracted where null was expected ([`autoresearch/eval.py`](autoresearch/eval.py)). Unrounded values and the historical baseline are in the [evidence note](docs/retrieval-extraction-evidence.md#extraction-replay). It is not F1 (output recorded before 2026-09 used `f1` key names; current output uses `field_acc`), and it is not a live-model grade.
- The replayed outputs are frozen, so a prompt or model change does not move the replay score. The replay catches scorer, schema and fixture regressions at zero cost; prompt and model changes are measured by the paid live eval job, which runs only when an API key is configured in CI.
- Three populations are separate and must not be summed: 28 committed prediction fixtures (the score population), 72 lookup cases in `autoresearch/eval_dataset_72.json` (44 have no committed prediction fixture yet), and the authoring corpus. See [three separate denominators](docs/retrieval-extraction-evidence.md#three-separate-denominators).
- The authoring corpus is stored as 202 JSONL lines; two of them are `_meta` rows, which the Results case count excludes. It is not the replay fixture total and not the score population.
- Retrieval recall, support (faithfulness) and abstention are **unmeasured**. The replay does not execute retrieval. See [retrieval measures are separate](docs/retrieval-extraction-evidence.md#retrieval-measures-are-separate).
- Held-out live-model performance is unmeasured until a funded run is logged ([protocol](docs/held-out-live-eval-protocol.md)).

**CI and merge enforcement**
- Since 2026-10-03, branch protection on `main` requires the CI `test` check. The weighted replay (eval-gate's Offline replay job) runs on eval-relevant PRs, pushes to `main` and a daily drift schedule, and it is **not** a universal required merge check. The earlier 2026-09-19 repository audit returned `Branch not protected` and an empty branch-rules list. See [CI and merge enforcement](docs/retrieval-extraction-evidence.md#ci-and-merge-enforcement).
- PR #32 (closed unmerged) was the intentional regression behind the failing-run demo. Its check failed because the fixtures were corrupted, not because the prompt edit alone changed predictions; live stages were skipped on that run (no key). Details: [docs/eval-gate-proof.md](docs/eval-gate-proof.md).
- The live-eval threshold gate and paid live eval run only when `ANTHROPIC_API_KEY` is configured in CI and are skipped otherwise. Drift recording and drift-issue creation sit inside the paid live job; the daily 13:23 UTC schedule reruns the offline replay.

**Tests, cost and latency**
- The test count in Results is from one local run on the date shown and changes as tests are added ([portfolio-metrics.yaml](docs/portfolio-metrics.yaml)). The 80% coverage figure is the CI floor, not a measured coverage figure.
- Cost and latency are modeled only until a funded `scripts/benchmark.py` run is committed ([cost-model.md](docs/cost-model.md)).

**Demo and screenshots**
- The screenshot shows the local fixture explorer with stored invoice output. It makes no live model call. Sample confidence values are stored metadata, not calibrated accuracy or the replay score. The walkthrough GIF is three actual browser states, not continuous video ([provenance](docs/screenshots/PROVENANCE.md)).
- The hosted Streamlit URL is intentionally omitted until anonymous access is verified. A static preview and trace visualizer live in [`site/`](site/) and [`frontend/pages/agent_trace.py`](frontend/pages/agent_trace.py).
- The package requires Python 3.12+ (`pyproject.toml` `requires-python`). The two standalone eval scripts use only the standard library and were run on Python 3.12; older versions are not tested.

**Feature scope**
- Deployment files are repository artifacts; a current live AWS deployment is not established here.
- PII filtering is pattern-based redaction (SSNs, credit cards, phone numbers, emails) in trace data. It does not establish complete PII detection or regulatory compliance.
- GraphRAG hybrid retrieval is opt-in (`GRAPH_RETRIEVAL_ENABLED=false` by default): regex entity graph, file-backed.
- The semantic cache ([ADR-0017](docs/adr/0017-semantic-cache-l1-l2.md)) is implemented but feature-flagged off and not wired into the extraction hot path.
- Langfuse, LangSmith and OpenTelemetry integrations require configuration and are not presented as verified live telemetry ([`app/observability.py`](app/observability.py)).
- There are two separate judges. The in-app judge (Gemini 2.5 Flash, Claude Haiku fallback) is off by default (`llm_judge_enabled = False` in `app/config.py`). The CI judge (`scripts/eval_llm_judge.py`) runs only in the paid live job, which skips without an API key, and falls back to Anthropic because the workflow passes no `--provider` and no Gemini key.
- The two-pass figures in [ADR-0003](docs/adr/0003-two-pass-extraction.md) (trigger rate, improvement, added latency) have no committed run artifact and are not cited as results here.

**Provenance:** built under a paid client engagement; an authorized walkthrough is available on request.

</details>

## Roadmap

- Record prediction fixtures for the 44 lookup cases that do not have one yet, so the replay covers all 72 ([eval dataset](autoresearch/eval_dataset_72.json)).
- Run the [held-out live eval protocol](docs/held-out-live-eval-protocol.md) and publish live-model accuracy next to the replay score.
- Measure retrieval recall, support and abstention on a labeled query set ([what is needed](docs/retrieval-extraction-evidence.md#retrieval-measures-are-separate)).
- Replace modeled cost and latency with a metered `scripts/benchmark.py` run ([cost model](docs/cost-model.md)).

## License

MIT
