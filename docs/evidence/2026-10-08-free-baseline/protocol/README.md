This is a local measurement candidate. No paid provider calls or held-out predictions exist. The runner and transport refuse live execution.

The frozen partition has 12 synthetic test cases (four invoices, four receipts, four purchase orders) and six separate dev cases. Original `test.json`, `train_dev.json` and `partition_manifest.json` hashes are unchanged. Fake tests use independent miniature documents. No corpus tuning or private client data is included.

The integration loads DocExtract source at 09a690bc9efc873ee59725c685a2ec604b6ef247 and a hash-bound extractor candidate containing one correction-call argument fix. See `correction-instructor.patch` and `RUN-PROPOSAL.md`. It reuses the actual Settings class with ambient environment/.env loading bypassed and synthetic credentials. Telemetry, database writes, active learning, citations and reflection are disabled. All provider clients share a metered mock transport with SDK retries disabled.

Thirty-two no-network tests pass. The suite covers all three document types through the candidate extractor, actual Instructor retries, correction calls, source-swallowed correction failures, router fallback blocked after unknown cost, cache TTL pricing, budget refusal, cancellation, model identity and runner artifact scoring. Socket connections are rejected during tests. Existing dependencies are reused, with no installation.

```sh
/Users/cave/Projects/clients/docextract/.venv/bin/python -m unittest discover -s outputs/measurement -v
ruff check outputs/measurement/*.py
ruff format --check outputs/measurement/*.py
```

The per-attempt ledger reserves before each send, prices separate cache/input/output usage, stores request hashes and usage metadata, and retains unresolved reservations. Any unknown-cost attempt stops later SDK retries, corrections and fallback sends. It does not save prompts, credentials or request headers. Runner artifacts retain failed and unattempted cases in the denominator; partial runs have no full primary score. Fake results cannot be published as performance results.

The [HTTPX transport contract](https://www.python-httpx.org/advanced/transports/) and [Anthropic caching usage categories](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) support the instrumentation design. Mock testing does not establish actual provider billing or extraction performance.

`RUN-PROPOSAL.json` records the proposed single-model $2 diagnostic, current price provenance and conservative reservations. Explicit funding, targeted partition/candidate lock commit and a reviewed guarded live activation remain pending. Keep RA10 and the existing release owner's work separate. Do not append results.tsv or modify saved golden responses. The existing 95.5% result remains a 28-fixture saved-prediction replay.
