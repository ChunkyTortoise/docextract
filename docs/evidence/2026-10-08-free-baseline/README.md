# Frozen Synthetic Document Extraction Evidence

Historical evidence snapshot, October 8, 2026. The owner accepted all 12 supported reference-label sets and the first-attempt API walkthrough. The owner reviewed all 12 full outputs on October 9, 2026, accepting all fields except three subtotal mappings under the chosen draft-only policy. See `human-review-status.json` for the exact scope. These accepted labels and trace do not establish complete extraction correctness.

One single-pass baseline using `nvidia/nemotron-3-ultra-550b-a55b:free` through anonymous Kilo produced 12 locally parsed and schema-validated predictions on 12 frozen synthetic text cases. The weighted reference-field score was 1.0, response-reported cost was USD 0, and nearest-rank latency was p50 15.287 seconds and p95 27.617 seconds. This score does not assess every output field. Seven cases contain nonempty unscored fields. Human review found three subtotal mappings that conflict with the accepted policy: a DRAFT estimate alone requires canonical subtotal null. The saved outputs contain 999 in invoice04, receipt04 and purchase_order04. All other saved fields were accepted.

The measured DocExtract source is `09a690bc9efc873ee59725c685a2ec604b6ef247`. This is a historical single-pass Nemotron baseline, not a measurement of current main, the production Anthropic/Instructor pipeline, or production accuracy. No retry, fallback or correction call occurred in the saved baseline. No OCR, PDF, database or deployed UI behavior is measured. Subjective portfolio ratings and hiring outcomes are separate.

## Offline verification

Use Python 3.12 or later. The reader and copied pure scorer use the standard library only. No API key, application settings, network or installation is required.

```sh
python3 verify_saved_run.py
```

Or pass this directory as the sole argument from another working directory. Exit 0 verifies the original saved run, corpus and source hashes, case coverage, request/prediction/filtered-response bindings, equality of attempts and run rows, and recomputed weighted reference-field score. Exit 1 reports a mismatch. The reader never calls the scorer’s benchmark CLI or writes golden responses or results.tsv.

Successful verification is of saved machine evidence. It does not rerun Pydantic validation, certify human correctness, or reproduce model predictions. The output explicitly states that human review is not verified by the reader. A later human review summary must carry its own actual decision evidence.

The original run SHA-256 is `9ba5b31ebb6b744d80e3a95e6e1901b2308f2902e41bf96f32be1897de906e5e`. The verifier pins that identity and the original test/scorer identities independently of the package manifest. Code provenance and hashes must still be reviewed before running any downloaded verifier. Manifest hashes are integrity evidence, not a cryptographic signature by a human reviewer.

## Contents and provenance

- `baseline/run.json` and `baseline/attempt-001.json` through `attempt-012.json` retain unmodified saved predictions, request bodies, usage and filtered receipts. The run also preserves original absolute paths as historical execution metadata.
- `corpus/test.json` holds 12 synthetic text cases, four invoices, four receipts and four purchase orders. `train_dev.json` holds six separate dev cases. `partition_manifest.json` binds their hashes and source prompts. No client/customer data was used.
- `source/` holds bound scorer, source prompts, schema definitions and injection-defense code. `run.json` and the execution binding identify the wider source inventory. This is a selected source export, not a complete runnable application checkout.
- `protocol/` preserves the original guarded Anthropic integration, candidate extractor, free adapter and retained tests/receipts. These are historical protocol evidence. Do not run a live adapter as part of offline verification.
- `receipts/` preserves prior independent metric recomputation, free-baseline preflight, original-file preservation verification and unscored-field flags. Agent reviews are not human acceptance.
- `manifest.json` records origins and hashes for every payload file, including the reader, documentation and derived human-review status. It excludes the manifest itself and its `manifest.sha256` sidecar to avoid a self-reference. The sidecar records the manifest digest. Human review and exact patch approval are still separate from hash integrity; a valid hash does not certify correctness or permission to publish.

The original guarded Anthropic scaffold README says no held-out predictions exist and cites 32 tests. Its manifest has an unmeasured status. Those statements describe the preserved original candidate, whose paid transport remains disabled. The later additive free adapter has the saved live evidence in `baseline/`; its preflight records 23 new socket-denied cases. The prior full measurement suite reported 55 passing tests. Those are historical test receipts; this package does not claim they were rerun during export.

## Protocol and scoring limits

The free adapter reuses source extraction prompts, injection guard, schemas and scorer, appending a JSON schema instruction to the system message. It differs from the production Anthropic/Instructor retry/correction pipeline. Raw response objects include `_confidence`; local parsing and schema normalization produce the saved predictions without that key. Schema validity alone does not establish source correctness.

Each case has weight1; declared critical fields receive weight2 within a case. The original scorer permits numeric tolerance, fuzzy string matching and expected-list matching. It assesses reference fields and does not penalize every unsupported extra field. The 1.0 result is weighted reference-field agreement, not complete extraction correctness. The saved source and references permit independent inspection of these rules.

All 12 attempts remain in the denominator. This run had no failed or unattempted cases and was not rerun to select a better score. A separate synthetic dev probe preceded it. The first attempted invoice01 is the walkthrough case, rather than a case selected by score.

The test cases were frozen separately from dev cases before this run, but have now been inspected by agents and reviewers. Future tuning followed by a rerun of these cases must disclose exposure. A new holdout requires a separately declared evaluation protocol and corpus; changing a filename does not restore holdout status.

Provider reasoning and raw response bytes are omitted. The saved filtered response can be checked against its own recorded hash. The raw-response hash cannot reconstruct omitted content. The provider-reported exact model and cost are retained in each receipt. The model ID is an alias, not independently verified immutable weights. Recorded free pricing does not establish future availability or authorize a paid fallback.

## Historical execution and runtime

The recorded invocation used the existing interpreter `/Users/cave/Projects/clients/docextract/.venv/bin/python`, the original measurement directory’s `free_baseline.py`, the output directory `live-free-baseline-oct8`, and `--live`. The run records the exact command, executable hash, source maps, request hashes, partition hashes and Python3.12.7/HTTPX0.27.2. It ran October 8, 2026, approximately15:35 to15:39 PDT.

The historical runner hardcodes a local source checkout. It is preserved unchanged. Portable saved-score verification uses the separate offline reader and copied bound scorer, so it does not require that checkout. The existing local environment inventory was captured during preparation and is not a historical dependency lock. Relevant currently installed versions include Pydantic2.9.2, Anthropic0.49.0 and Instructor1.17.0; these do not by themselves prove fresh-install or live-run reproduction.

No inference rerun is part of this package preparation. A later live reproduction needs a reviewed portable setup, fresh free-provider/pricing checks and fail-closed guards, or an explicit numeric paid cap. Any new attempt uses a new output directory and retains failures. An external alias can change, so even a correctly configured later call need not reproduce these predictions bit for bit.

## Human review and publication

The owner has accepted the frozen reference values for all 12 cases and the existing first-attempt API walkthrough. Full-output review is recorded for every case. The accepted policy requires canonical subtotal null when only a DRAFT estimate is supplied, preserving draft text separately. Three saved subtotal999 values are disclosed prediction findings. See `adjudication-summary.json` for source spans and values. All other saved fields were accepted. No reference-label change or rescore is warranted. Original predictions, labels and score remain unchanged. This review does not establish complete extraction correctness beyond the reviewed sample.

Review disagreements enter a versioned adjudication ledger. Label-only changes may rescore saved predictions without inference, retaining original and revised scores. No frozen evidence is silently edited. Human acceptance is recorded only for its actual stated scope. No public claim approval or hiring impact is inferred from this package or from an automated check. Publication requires the final human-reviewed package, exact diff review and applicable Git/publication approvals.
