# Sprint 4 patch — Original-query-first retrieval

## Why this patch exists

Earlier `/agent/ask` called the LLM Planner **before** its first BM25 search. The Planner could rewrite an already precise scientific question and lose useful terminology. This patch makes the original user question the **mandatory first BM25 query**, before the LLM is called.

It is an **overlay** for the existing Marine Evidence Finder **Sprint 4** implementation, not a complete project. No database migration or new dependency is required. No changes to `/ask`, the ingestion/recovery pipeline, PostgreSQL, Redis, or the Prometheus configuration.

## Behaviour after patch

1. Validate the original question (`2..4000` characters), the maximum number of decisions, and `top_k`.
2. Run `index.search(question, top_k=top_k, distinct_pages=distinct_pages)` using the original wording (apart from `strip()` at input validation).
3. Store the returned passages in `evidence` and put an automatic `search_bm25` record at `trace[0]` with `step=0` and `origin="original_question"`.
4. Mark the original query as already searched to prevent redundant BM25 calls.
5. **Only now** call the LLM Planner. It sees the original question, the initial evidence excerpts, and the initial search event. It can `finish`, `expand_context`, `search_bm25` with different words, or `abstain`.
6. Preserve initial passages in the bounded evidence collection when later searches run; pass the **original question** to the final generator.

`steps` continues to mean **LLM Planner decisions** (up to `max_steps`, default 5). The automatic step 0 is not an LLM decision; it is included in `trace` and **does** count toward `tool_calls` and the Prometheus tool-call counter. So a run with one initial BM25 search and a single `finish` decision reports `steps=1`, `tool_calls=1` and **two trace events**.

The original-first search **does not** mean the first query will always find good evidence. An empty first retrieval does not prevent the Planner from searching again. As before, citation ID verification does not establish semantic entailment, and repeated search strings or exhausted budgets can terminate without an answer.

## Installation (Windows PowerShell; run from project root)

```powershell
$cfg = @(
  '-f', 'compose.yaml',
  '-f', 'compose.postgres.yaml',
  '-f', 'compose.metadata.yaml',
  '-f', 'compose.jobs.yaml',
  '-f', 'compose.observability.yaml'
)

# Review and save local uncommitted modifications before overwriting code.
git status --short

Expand-Archive `
  "$env:USERPROFILE\Downloads\marine_sprint4_original_first_patch.zip" `
  -DestinationPath . -Force

python -m pytest -q
python scripts/smoke_agent.py

docker compose @cfg up -d --build --no-deps api ui
```

Only `api` and `ui` need rebuilding: Python code changed in the API container and the Streamlit UI. No need to restart workers, reconciler, Redis, PostgreSQL, Prometheus, or Grafana. **Do not run `down -v`.**

## Offline smoke test expected evidence

```text
PASS: exact original question -> BM25 -> bounded planner -> context -> cited answer
"step": 0,
"origin": "original_question",
"query": "What did hydrophones record?"
```

The smoke test is deterministic and does not spend OpenAI tokens.

## Optional real integration test — requires configured OpenAI key and is paid

```powershell
python scripts/smoke_agent.py --live `
  --question "How does anthropogenic underwater noise affect harbour porpoise foraging behaviour?"
```

Check the response's `trace[0]`: it must contain the **identical original question** (other than surrounding whitespace), `origin=original_question`, and `step=0`. The Planner may perform additional searches or finish. If the corpus does not contain relevant evidence, `insufficient_evidence` is a valid result. For inspectability, the same step is displayed in the Streamlit Agent tool trace as "Step 0 (automatic original-question search)".

## Files in this ZIP

- `src/marine_evidence/agent.py` — mandatory initial retrieval, original evidence preservation, correct counting, Planner instruction update
- `tests/test_agent.py` — adjusted regressions and four new original-first tests
- `scripts/smoke_agent.py` — offline/live assertions for step 0
- `streamlit_app.py` — clear display of the automatic search vs Planner decisions
- `README_SPRINT4_ORIGINAL_FIRST_PATCH.md` — this guide

## Verification scope

Locally, with the full merged Sprint 4 project: **142 passed, 5 skipped** (skipped tests require test PostgreSQL). Offline smoke passed. A live OpenAI request and Docker build were **not** performed in this environment; run them on your machine.
