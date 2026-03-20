# Docextract Autoresearch Agent

## Mission
Maximize extraction accuracy on 6 real-world document types by mutating `autoresearch/prompts.yaml` one change at a time, running the eval harness, and keeping improvements.

**Target metric:** weighted field-level accuracy (0.0–1.0). Higher is better.
**Eval command:** `python -m autoresearch.eval`
**One cycle:** ~20 seconds, ~$0.03.

---

## The Loop

```
1. Read current prompts.yaml and results.tsv (understand what's been tried)
2. Form a hypothesis: which prompt or param change might improve accuracy?
3. Edit prompts.yaml — ONE change per cycle
4. git add autoresearch/prompts.yaml && git commit -m "autoresearch: <what you changed>"
5. python -m autoresearch.eval
6. Read the SCORE from stdout
7. If SCORE > best_score:
       Keep commit. Record best_score = SCORE.
   Else:
       git reset --hard HEAD~1
       (discard the change — it didn't help)
8. NEVER STOP. Go to step 1.
```

---

## What You May Edit

**Only `autoresearch/prompts.yaml`.** Nothing else.

You can change:
- `extract_system_prompt` — instructions given to Claude before the user message
- `extract_prompt` — the user message template for Pass 1 extraction
- `correction_prompt` — the user message template for Pass 2 correction
- `classify_prompt` — the classification prompt (affects doc_type routing)
- `params.extract_text_limit` — how many chars of text Claude sees (default 8000)
- `params.correction_text_limit` — chars visible in correction pass (default 3000)
- `params.classify_text_limit` — chars for classification (default 2000)
- `params.extraction_confidence_threshold` — confidence below which correction fires (default 0.8)
- `params.classification_confidence_threshold` — confidence below which "unknown" is returned (default 0.6)

**Do NOT change:**
- `params.max_chunk_tokens` or `params.overlap_chars` (chunking, not eval bottleneck)
- Any file outside `autoresearch/prompts.yaml`
- The eval dataset (`eval_dataset.json`)
- The scoring logic (`eval.py`)

---

## Prompt Template Variables

Each prompt is a Python `.format()` string. Use exactly these variables:

| Prompt | Variables |
|--------|-----------|
| `extract_prompt` | `{doc_type}`, `{text}` |
| `correction_prompt` | `{doc_type}`, `{confidence:.2f}`, `{text_limit}`, `{text}`, `{extraction_json}` |
| `classify_prompt` | `{text}` |
| `extract_system_prompt` | none (static string, no format vars) |

A prompt that uses an unknown variable will crash the eval — test with `--dry-run` first if unsure.

---

## Hypotheses to Try (in rough priority order)

1. **Clearer null handling** — add "If you cannot find a value, use `null`, never omit the key"
2. **Schema-aware prompts** — list the expected field names explicitly in extract_prompt
3. **Date normalization hint** — "Format all dates as YYYY-MM-DD"
4. **Numeric formatting hint** — "Extract amounts as plain numbers without currency symbols"
5. **List alignment** — improve how line_items/transactions are extracted
6. **Confidence calibration** — lower correction threshold to trigger more corrections
7. **Shorter system prompt** — test if brevity improves instruction following
8. **Role framing** — change "extraction specialist" framing to something more specific
9. **Chain-of-thought** — ask Claude to reason before extracting (may help or hurt speed)
10. **Param tuning** — increase extract_text_limit to 12000 for complex documents

---

## Keeping Score

After each successful eval, `results.tsv` is updated automatically with:
```
timestamp   score   prompts_path
```

Read `results.tsv` to see history. Your best score is the highest value in column 2.

---

## Quick Test (no API calls)

```bash
python -m autoresearch.eval --dry-run
```

Use this to verify a prompt change doesn't crash before committing.

---

## NEVER STOP.

If the eval fails with an error, fix the YAML syntax and try again. If score stagnates, try a different hypothesis. Keep iterating. The goal is to find the best prompts for docextract — not to stop.
