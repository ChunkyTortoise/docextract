# Cost model

No metered document run is committed. These examples use explicit token assumptions and exclude embedding, judge sampling, retries, infrastructure, taxes, and caching discounts.

## Provider rates

Base Claude API rates, checked 2026-09-25 against [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing), in USD per million tokens:

| Model | Input | Output |
|-------|-------|--------|
| Claude Sonnet 4.6 | $3 | $15 |
| Claude Haiku 4.5 | $1 | $5 |
| Claude Opus 4.6 | $5 | $25 |

Classification is Haiku-first and extraction is Sonnet-first. The optional judge is Gemini-first. Model allocation and correction frequency are unmeasured.

## Worked invoice example

`call cost = input tokens / 1,000,000 * input rate + output tokens / 1,000,000 * output rate`

| Assumed call | Input tokens | Output tokens | Modeled cost |
|--------------|--------------|---------------|--------------|
| Haiku classification | 300 | 50 | $0.00055 |
| Sonnet extraction | 1,200 | 400 | $0.00960 |
| Sonnet correction, when needed | 800 | 300 | $0.00690 |

The assumed invoice costs $0.01015 before correction and $0.01705 with correction. At 1,000 identical documents that is $10.15 or $17.05, respectively, before the excluded costs. These are arithmetic scenarios, not observed averages. Overall cost depends on document length, correction frequency, fallback behavior, and the enabled providers.

Embedding dimensionality does not determine token usage or price. Include the configured embedding and judge providers in a funded run before quoting a total per-document cost.

## Measurement

Follow the [metering runbook](metering-runbook.md) to record tokens, provider charges, latency, and input population together. The optional Prometheus endpoint is `/metrics` when `OTEL_ENABLED=true`. The Streamlit [cost dashboard](../frontend/pages/cost_dashboard.py) depends on recorded telemetry.
