# Sprint 4.3 — Token & Cost Observability

Overlay on top of Sprint 4.2. Only telemetry and the comparison harness changed;
answer prompts, citation validation, models, retrieval, and planner budgets remain unchanged.
No migration, dependency, or volume reset is required.

## What is measured

The API creates a request-local `UsageLedger` in `/ask` and `/agent/ask` using
`ContextVar`. The shared `tracked_create` wrapper around `client.responses.create`
in `answer.py` (generator) and `agent.py` (planner) records provider usage immediately
on return, before JSON/status/citation validation. It counts logical SDK invocations,
not HTTP attempts inside the SDK. An incomplete response may have billable usage.
An exception without a response is counted, but its token counts and cost are unknown.
The API publishes accumulated measurements in a `finally` block, including HTTP 502s.
Direct library calls/CLI outside a usage scope are not instrumented by default.

Successful API responses add `llm_usage`, with `llm_calls`, `input_tokens`,
`cached_input_tokens`, `output_tokens`, `reasoning_tokens`, `total_tokens`,
`unpriced_calls`, `known_cost_usd`, `estimated_cost_usd` and per-call `calls`
(role, returned/requested model, response status, service tier, token counts,
price used in USD per million tokens, and estimate). A null aggregate means at least
one relevant count is unknown. A null cost means at least one call is unpriced;
`known_cost_usd` is only the subtotal of priced calls. An actual zero-call run has
zero cost and zero tokens. HTTP error response bodies retain the original contract;
look at metrics/logs for their usage, not the successful-result JSON schema.

## Pricing

`config/llm_prices.json` holds standard text API rates in USD per million tokens.
The supplied GPT-5 mini alias and snapshot use $0.25 input, $0.025 cached input,
$2 output, verified 2026-11-24 from:
https://developers.openai.com/api/docs/models/gpt-5-mini

Cost = ((input - cached) * input_rate + cached * cached_rate + output * output_rate) / 1e6.
Cached input is included in input tokens; reasoning is included in output tokens.
Neither is added again. `total_tokens` is input + output. See
https://developers.openai.com/api/docs/guides/reasoning

Example using a fake provider response: 1000 input, 200 cached, 500 output,
300 reasoning gives $0.001205; two such calls cost $0.002410. Not real measurements.
Rates are keyed to the **returned model**, never an assumed fallback. Add exact
model IDs and validated standard rates to the catalog if you switch models.
Unknown model, missing cached-input/total usage or unsupported service tier -> null
estimate, not zero. Missing service tier is assumed standard because this app does
not request a tier. Rates load when the API is created; restart API after editing.
Docker mounts the file read-only; other installations may set MARINE_LLM_PRICES_PATH.
The catalog does not support cache-write pricing, additional service charges,
regional uplifts, discounts, credits, taxes, or non-standard tiers. Do not add models
with incompatible pricing to it without extending the formula. Estimates are not
an invoice, exact billing ledger, or a spending cap. SDK retries and requests without
usage can incur unobserved costs. No API billing/admin credentials required.

## Metrics

Existing metrics remain intact. New process-local counters:

- `marine_llm_calls_total{mode,role,response_status}`: logical SDK invocations
- `marine_llm_tokens_total{mode,role,kind}`: observed counts (four kinds; do not sum subsets)
- `marine_llm_missing_token_fields_total{mode,role,kind}`: unavailable counts
- `marine_llm_estimated_cost_usd_total{mode,role}`: priced calls only
- `marine_llm_unpriced_calls_total{mode,role}`: calls without estimates

Fixed labels only; no model names, user questions, chunk IDs or request IDs in metrics.
The structured event `llm_usage_summary` contains aggregate counts and request ID
(from existing logging middleware), not prompts or answers. Counters reset on API
process restart; Prometheus retains scrape history according to its retention.
Grafana's existing dashboard has five additional panels. Cost and unpriced panels
show process-lifetime counts. Rate panels require enough scrape samples; zero rates
are expected during inactivity. Do not interpret partial cost as full spend.

## Install and verify (PowerShell)

From the root of your current project, extract the ZIP overlay, preserving data:

```powershell
Expand-Archive "$env:USERPROFILE\Downloads\marine_sprint4_3_cost_observability.zip" -DestinationPath . -Force
python -m pytest -q
python scripts/smoke_agent.py
$cfg = @('-f','compose.yaml','-f','compose.postgres.yaml','-f','compose.metadata.yaml','-f','compose.jobs.yaml','-f','compose.observability.yaml')
docker compose @cfg config --services
docker compose @cfg up -d --build api ui
docker compose @cfg restart grafana
docker compose @cfg ps
Invoke-RestMethod http://127.0.0.1:8000/health/ready
python scripts/smoke_observability.py
```

Use the updated benchmark script directly (no regex patch or top-12 copy needed).
This next command makes paid API requests: five baseline workflows and five agent
workflows, potentially up to 35 logical calls with the default 5-decision budget.

```powershell
python scripts/eval_agent_vs_ask.py `
  --confirm-paid `
  --benchmark evaluation/benchmark_agent_synthesis.jsonl `
  --split test --limit 5 --mode both --baseline-top-k 12 `
  --output data/agent_cost_comparison.jsonl
```

To use only one mode, use `--mode baseline` or `--mode agent`. Baseline defaults to
4 chunks for compatibility; the agent still starts with 4 and may collect up to 12.
JSONL stores `llm_usage` and the parameters for each workflow; older records do not
contain historical usage. Errors are stored separately; aggregate known costs in
successful benchmark records exclude failed HTTP requests, which are captured when
possible in server metrics. Inspect both when reconciling. Keep previous runs.

```powershell
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/metrics).Content `
  -split "`n" | Select-String '^marine_llm_.*_total\{'
```

Dashboard: http://127.0.0.1:3000/d/marine-reliable-ai-s3

## Acceptance and limits

- Local reconstruction from original user archive plus Sprint 2 through 4.2 overlays:
  173 passed, 5 skipped; offline smoke passed. Test clients use simulated provider usage.
- Docker, real OpenAI responses and live Grafana provisioning require verification in
  the user's environment. No paid calls were made to prepare this overlay.
- Same five questions serve as regression, not independent test. Repeated model
  outputs can vary; equal maximum chunk counts are not equal token counts.
- Partial/abstention semantics, PDF unit extraction, holdout evaluation and adaptive
  routing are separate follow-up tasks. This patch intentionally leaves prompts unchanged.
