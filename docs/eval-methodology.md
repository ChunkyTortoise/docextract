# Eval Methodology

This document explains how DocExtract measures prompt quality, enforces regression gates in CI, and detects silent model drift in production.

---

## 1. Why the eval gate exists

Prompts are code. A two-line edit to an extraction prompt can silently reduce field recall on medical records by 8% while appearing to improve invoice performance in a quick smoke test. Without automated measurement, these regressions reach production and surface only in user complaints.

DocExtract runs three complementary eval frameworks on every pull request that touches a prompt or extraction service. A merge-blocking gate compares each metric against a stored baseline and rejects the PR if any metric regresses beyond the tolerance threshold. On merge to main, the baseline auto-advances when metrics improve.

This design was chosen over simpler unit tests because extraction quality is inherently probabilistic: the same prompt on the same document can produce correct output on one run and a structurally valid but semantically wrong output on another. Deterministic assertions catch schema violations; probabilistic metrics catch semantic drift.

---

## 2. The stack at a glance

```
┌─────────────────────────────────────────────────┐
│  Pull request touches prompts/** or services/**  │
└────────────────────┬────────────────────────────┘
                     │
         ┌───────────┼───────────┐
         ▼           ▼           ▼
   Promptfoo      Ragas       LLM-judge
 (deterministic)  (RAG        (open-ended
  assertions)    metrics)      rubric)
         │           │           │
         └───────────┼───────────┘
                     ▼
              eval_gate.py
         (compare vs baseline.json)
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
       Block       Pass      Auto-bump
       merge      merge      baseline
                     │
               Langfuse
         (prod telemetry + prompt registry)
```

**Promptfoo** runs deterministic assertions: valid JSON output, no prompt-injection artifacts, latency under 8 seconds. Fast, cheap, runs on every PR regardless of which files changed.

**Ragas** computes RAG-specific metrics against the golden set: faithfulness, answer relevancy, and context precision. These require LLM calls so they cost more; they run on PRs that touch prompts or extraction services.

**LLM-as-judge** applies a 5-criterion rubric to each extraction output, aggregating scores across N=3 samples for self-consistency. This catches quality issues that structured metrics miss, such as over-verbose explanations in the output or fields that are technically present but imprecise.

**Langfuse** is the production telemetry layer. It receives span data from every live extraction via `AnthropicInstrumentor`, stores prompt versions in its registry, and provides per-trace debugging when a prod failure warrants investigation.

---

## 3. The golden set

The golden set (`evals/golden_set.jsonl`) contains 51 hand-labelled documents across six categories:

| Category | Count | Notes |
|---|---|---|
| invoice | 18 | Includes partial payment, credit memo, B2B PO, EUR/foreign currency |
| receipt | 10 | Gas, restaurant, retail, online, refund, split tender |
| purchase_order | 8 | Multi-item, blanket, change order, services, emergency/sole-source |
| bank_statement | 6 | MXN, joint account, wire transfer, overdraft |
| medical_record | 6 | Pediatric visit, lab results, prescription history, surgery note |
| identity_document | 3 | US passport, Mexican passport, CA driver's license |

**Selection criteria:** Each case targets a distinct failure mode. The invoice set includes a credit memo (negative total) and a partial-payment case (balance due != invoice total) because these tripped early versions of the extractor. The medical set includes Arabic, Chinese, and Spanish names because OCR pipelines frequently mangle non-ASCII characters before extraction.

**Ground truth contexts** are verbatim spans from `input_text` (1-3 sentences) that contain the critical-field values. These are used by Ragas for `context_precision` scoring. All 51 cases have manually selected spans; none use the auto-derived sliding-window stubs from the initial migration.

**Diversity guardrails** applied during authoring:
- OCR noise injected in 4 cases (collapsed spaces, `O`/`0` substitutions, dropped diacritics)
- Non-English vendor/customer names in 9 cases (Ghanaian, Latin American, Arabic, Japanese, South Asian)
- Non-USD currencies in 4 cases (EUR, JPY, MXN)
- Negative or zero amounts in 3 cases
- Ambiguous date formats in 2 cases

**Failure-mining rotation:** The current 51-case set was constructed from first-principles. Once the harness has been running for 30+ days in production, new cases will be mined from Langfuse traces where extraction confidence was low or where downstream validation rejected the output.

---

## 4. Metrics and thresholds

| Metric | Source | Floor | Rationale |
|---|---|---|---|
| `faithfulness` | Ragas | 0.85 | Measures whether extracted claims are grounded in the source text. Below 0.85 means the extractor is hallucinating fields. |
| `answer_relevancy` | Ragas | 0.80 | Measures whether the response is focused. Low scores indicate verbose or off-topic output. |
| `context_precision` | Ragas | 0.75 | Measures whether the right document spans were used. Lower tolerance because this metric is sensitive to verbatim span quality. |
| `extraction_f1` | LLM-judge | 0.90 | Field-level precision/recall aggregate. High floor because field extraction is the core product function. |
| `judge_pass_rate` | LLM-judge | 0.80 | Fraction of rubric criteria passed across all cases. |

In addition to absolute floors, no metric may drop more than **3%** relative to the current baseline in a single PR. This prevents a sequence of small regressions that each stay above the floor but compound over time.

The 3% threshold was calibrated against the historical variance in the first 28-case baseline run. One standard deviation of variation across three independent runs was approximately 1.5%, so 3% catches real regressions with low false-positive rate.

---

## 5. Baseline and thresholds

`autoresearch/baseline.json` stores the most recent accepted score set. It is committed to the repository so baseline changes appear in PR diffs and are code-reviewable.

**Auto-bump rules:** When a PR merges to main and all metrics pass their floors, `eval_gate.py` checks whether any metric improved by more than 1% relative to baseline. If so, it writes an updated `baseline.json` and commits it with message `chore(eval): bump baseline [skip ci]`. The `[skip ci]` token prevents a recursive eval run.

**Manual baseline reset:** After a planned prompt rewrite or corpus expansion, run `make eval && make eval-baseline` locally and commit the result. The CHANGELOG entry should document the reason and include a before/after table.

**No-mixed-commit rule:** Commits that touch both `prompts/**` and application code in the same commit make bisection harder. The pre-commit hook in `.pre-commit-config.yaml` rejects these. Prompt-only changes get a `prompt/` branch prefix and a `prompt/<family>-vX.Y.Z` git tag on merge.

---

## 6. Promptfoo config walkthrough

`promptfooconfig.yaml` defines the deterministic assertion layer:

```yaml
providers:
  - id: anthropic:messages:claude-sonnet-4-6
    config:
      temperature: 0      # deterministic for CI
      max_tokens: 2048

prompts:
  - label: extraction-v1.1
    raw: "file://prompts/extraction/v1.1.0.txt"
  - label: extraction-v1.0
    raw: "file://prompts/extraction/v1.0.0.txt"

tests: evals/promptfoo_tests.jsonl

defaultTest:
  assert:
    - type: is-json
    - type: not-contains
      value: "SYSTEM OVERRIDE"    # prompt injection artifact
    - type: not-contains
      value: "exfil"              # data exfiltration string
    - type: latency
      threshold: 8000             # ms
```

Test cases in `evals/promptfoo_tests.jsonl` are generated from `evals/golden_set.jsonl` by `scripts/generate_promptfoo_tests.py`. Each record maps `input_text` to `{{text}}` and `doc_type` to `{{doc_type}}`, with per-case assertions for schema validity and critical-field presence.

The `passRateThreshold: 0.85` setting causes Promptfoo to exit non-zero when fewer than 85% of assertions pass, which fails the CI step.

---

## 7. Ragas integration and cost control

Ragas requires both a retriever and a generator. For DocExtract:

- **Retriever**: `ground_truth_contexts` from the golden set (pre-fetched verbatim spans, not a live retrieval call)
- **Generator**: `expected_output` from the golden set as the reference answer, compared against the actual extraction output

This setup avoids a live pgvector query per eval case, which would couple the metric score to retrieval quality and make the metric harder to interpret in isolation.

**Cost control:** Ragas calls the LLM twice per case (once for faithfulness, once for answer relevancy). At 51 golden cases, that is ~102 LLM calls per run. The `eval-gate.yml` workflow skips Ragas on PRs that do not touch `prompts/**` or `app/services/extraction/**`, keeping the common path (pure code change) cheap.

`context_precision` requires an embedding model. `scripts/eval_ragas.py` uses `OPENAI_API_KEY` for text-embedding-3-small by default; this can be swapped to a local embedding model by setting `RAGAS_EMBEDDING_MODEL=local`.

---

## 8. LLM-as-judge rubric

The judge script (`scripts/eval_llm_judge.py`) applies a 5-criterion rubric to each extraction output:

1. **Field completeness** -- Were all extractable fields returned?
2. **Field accuracy** -- Do field values match the source document?
3. **Null discipline** -- Were non-present fields returned as null rather than hallucinated?
4. **Schema compliance** -- Does the output conform to the expected JSON schema?
5. **PII safety** -- Were raw PII fields (SSN, card numbers) masked or omitted per the safety spec?

Each criterion is scored pass/fail with a brief rationale. The judge calls the model N=3 times per case and takes the majority vote across criteria, which reduces variance from a single call. All rubric prompts are logged to Langfuse as generations under the `eval-run` trace, enabling manual review of any surprising failures.

The rubric prompt itself is versioned in `prompts/extraction/` alongside the extraction prompt so rubric changes are also code-reviewable.

---

## 9. Pull request lifecycle

```
1. git checkout -b prompts/extraction-my-fix
2. Edit prompts/extraction/v1.2.0.txt  (new file; do NOT mutate old versions)
3. Update prompts/CHANGELOG.md (rationale + placeholder metrics table)
4. make eval-fast  (Promptfoo only, ~20s, use while iterating)
5. make eval       (full suite, ~4 min, run before push)
6. git push && open PR
7. eval-gate.yml runs full suite
8. marocchino/sticky-pull-request-comment posts metric table to PR
9. Merge if all gates pass
```

The sticky comment shows a before/after table:

```
| Metric            | Baseline | PR     | Delta  | Status |
|-------------------|----------|--------|--------|--------|
| faithfulness      | 0.881    | 0.897  | +0.016 | PASS   |
| answer_relevancy  | 0.842    | 0.840  | -0.002 | PASS   |
| context_precision | 0.763    | 0.771  | +0.008 | PASS   |
| extraction_f1     | 0.912    | 0.934  | +0.022 | PASS   |
| judge_pass_rate   | 0.847    | 0.863  | +0.016 | PASS   |
```

The comment is updated on each push to the PR so stale scores never linger.

---

## 10. Main-branch lifecycle

When a PR merges to main with passing metrics:

1. `eval-gate.py` checks whether any metric improved more than 1% vs baseline.
2. If yes: writes updated `autoresearch/baseline.json` and commits it (`chore(eval): bump baseline`).
3. `scripts/sync_langfuse.py --all --label production` runs to promote the new prompt version in Langfuse registry.
4. CI creates the git tag `prompt/<family>-vX.Y.Z` pointing at the merge commit.

If the PR improved nothing (pure code refactor, no metric change), the baseline is left unchanged.

---

## 11. Daily drift cron

The scheduled cron (13:23 UTC daily) runs the golden set against the **production** Langfuse prompt version rather than HEAD. This detects silent drift caused by upstream model updates, embedding API changes, or token-level behavior shifts that do not require code changes to manifest.

`scripts/eval_drift_record.py` appends one JSONL row per metric to the `eval-history` branch. The cron step in `eval-gate.yml` then runs a z-test:

1. Load the last 7 daily records per metric.
2. Compute mean and standard deviation.
3. Compute z-score: `z = (today - mean) / stdev`.
4. Flag drift if `|z| > 2.0` on any metric, or if 3 consecutive days trend the same direction by more than 1 standard deviation.

On a drift flag, the workflow opens a GitHub issue (not a build failure) with:
- The z-score table
- Langfuse trace links for the 5 worst-scoring golden cases
- The diff between today's scores and the 7-day mean

The issue-not-failure design is intentional. Drift does not mean the current release is broken; it means the distribution shifted and warrants investigation. Blocking deploys on every z-test trigger would create too much noise given the sensitivity of probabilistic metrics.

---

## 12. Cost and runtime budget

| Component | Cost per run | Wall-clock |
|---|---|---|
| Promptfoo (51 golden × 2 prompts) | ~$0.04 | ~25s |
| Ragas (51 cases × 2 LLM calls) | ~$0.18 | ~90s |
| LLM-judge (51 cases × N=3) | ~$0.22 | ~120s |
| **Total per PR eval** | **~$0.44** | **~4 min** |
| Daily drift cron | ~$0.18 | ~90s |

The budget stays under $0.50 per PR because:
- Promptfoo uses `temperature: 0` (maximally cache-friendly)
- Ragas skips embedding re-computation when `ground_truth_contexts` are pre-fetched
- LLM-judge uses `claude-haiku-4-5` for the rubric scoring rather than Sonnet

Total monthly cost at 20 PRs/month: ~$9 in API calls plus GitHub Actions runner time (included in free tier for public repos).

---

## 13. How the harness caught a real regression

*Note: The following is a representative case study. The harness caught this class of regression during development. The specific PR number and exact figures are synthetic placeholders; they will be replaced with a real incident once the harness has been running in production for 60+ days.*

**The bug:** Extraction prompt v1.1.0 added a "rate your confidence 1-10" instruction to improve interpretability. This inadvertently caused the model to prepend a confidence preamble before the JSON output on approximately 20% of cases, breaking `is-json` assertions and causing Ragas faithfulness to drop from 0.881 to 0.743.

**How it was caught:** The Promptfoo `is-json` assertion failed on 11 of 51 cases immediately, blocking the PR. The sticky comment showed faithfulness dropping 13.8 percentage points (far outside the 3% tolerance).

**The fix:** Moved the confidence instruction inside the JSON schema definition (`"confidence": "rate 1-10"` as a field spec) so the model returned confidence as a structured field rather than a preamble.

**The lesson:** JSON extraction prompts must constrain all output to the schema. Any instruction that could plausibly appear before the opening `{` will sometimes appear before the opening `{`.

---

## 14. What we would do at 10x scale

**Shard the golden set:** At 500+ cases, the 4-minute eval run becomes a 40-minute blocker. Shard by doc_type so PRs touching only the invoice extractor run the invoice subset (18 cases, ~30 seconds).

**Regression DAG:** Track per-case scores over time. When a case transitions from pass to fail between two commits, surface it in the PR comment as a regression fingerprint rather than requiring manual diff.

**Eval-on-every-commit vs PR-only:** Commit-level evals are feasible with a fast subset (Promptfoo only, 5-10 cases, <$0.01). Use these in a pre-merge check while saving the full suite for the PR gate. This gives faster feedback during development without blowing the monthly budget.

**Golden set rotation:** Retire cases that have passed every eval for 90 consecutive days (they add cost without marginal signal). Add cases mined from Langfuse traces where confidence < 0.7 or downstream validation rejected the output.

**Parallelism:** The three eval scripts currently run sequentially. Running Ragas and LLM-judge in parallel would cut wall-clock from ~4 minutes to ~2.5 minutes with no cost change.

---

## 15. Appendix: Runbooks

### Updating a prompt

1. Create `prompts/<family>/v<next>.txt` with your changes.
2. Add a frontmatter comment on line 1: `# langfuse: docextract-<family>@v<next>`
3. Update `prompts/CHANGELOG.md` with rationale + placeholder metrics table.
4. Run `make eval-fast` while iterating, then `make eval` before pushing.
5. Open a PR. The eval gate will post a metric table as a sticky comment.
6. On merge, run `python scripts/sync_langfuse.py --family <family> --version <next>` to promote in Langfuse.

### Rolling back a prompt

1. Revert the merge commit in git: `git revert <sha>`.
2. The eval gate will run on the revert PR and confirm scores return to baseline.
3. Run `python scripts/sync_langfuse.py --family <family> --version <previous> --label production` to demote the bad version in Langfuse.

### Investigating a drift issue

1. Open the GitHub issue created by the cron job. The z-score table identifies which metric drifted.
2. Click the Langfuse trace links for the 5 worst cases. Compare the extraction output against `expected_output` in the golden set.
3. Common causes: Anthropic model updates (check the Anthropic changelog), embedding API changes (affects context_precision), or a data distribution shift in prod that the golden set does not represent.
4. If the drift is real and persistent: add new golden cases from prod traces that cover the drifted distribution, regenerate baseline, open a PR to update the prompt.

### Rotating the golden set

1. Export Langfuse traces where extraction confidence < 0.7 or downstream validation rejected output.
2. For each candidate case: write `input_text` from the source document, manually compute `expected_output`, select 1-3 verbatim `ground_truth_contexts` spans.
3. Add to `evals/golden_set.jsonl`. Run `scripts/generate_promptfoo_tests.py` to regenerate `evals/promptfoo_tests.jsonl`.
4. Run `make eval && make eval-baseline` to establish a new baseline. Document in `evals/CHANGELOG.md`.
5. Retire cases that have passed every eval for 90 consecutive days to keep the set size under 100 cases.

### Resetting the baseline after corpus expansion

After adding new (harder) cases, the overall score will drop. This is expected. Run:

```bash
make eval             # full suite against new corpus
make eval-baseline    # write new autoresearch/baseline.json
```

Then document in `evals/CHANGELOG.md` that the baseline drop reflects corpus expansion, not a prompt regression, so future PRs interpret the new floor correctly.
