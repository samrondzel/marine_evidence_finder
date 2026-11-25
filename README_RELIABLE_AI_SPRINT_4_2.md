# Sprint 4.2 — Reliable Agentic RAG

## Install (PowerShell, from project root)

This is an overlay for the project after Sprint 4, Original Query First and the LLM budget fix. It replaces seven code/test files and adds this README. No database migrations, new dependencies, Docker volumes or corpus files are required. Save local changes before overwriting.

```powershell
 git status --short
 Expand-Archive "$env:USERPROFILE\Downloads\marine_sprint4_2_reliable_agent.zip" -DestinationPath . -Force
 python -m pytest -q
 python scripts/smoke_agent.py
 $cfg = @('-f','compose.yaml','-f','compose.postgres.yaml','-f','compose.metadata.yaml','-f','compose.jobs.yaml','-f','compose.observability.yaml')
 docker compose @cfg config --services
 docker compose @cfg up -d --build api ui
 docker compose @cfg ps
 Invoke-RestMethod http://127.0.0.1:8000/health/ready
 python scripts/smoke_observability.py
```

Expected in reconstructed test copy: 163 passed, 5 skipped, 3 Alembic deprecation warnings; offline smoke PASS. The API and UI both need rebuilding because the answer contract changed. Do not use `--remove-orphans` or delete volumes.

## What changed

- Original-question BM25 remains first. No additional planning request before it. Default top-k=4 and max planner decisions=5 (maximum 6), evidence cap=12. The token budgets remain planner 4096, generator 8192. These are per-call limits, not an end-to-end time/token/cost guarantee.
- `run_research_agent`: distinguish stop reason from answer status. On `agent_finished`, `agent_abstained`, `step_limit`, `evidence_limit`, or `no_progress`, finalize once using accumulated evidence (no generator if zero hits). Thus planner abstention with evidence is now a stop signal, not a final refusal. No extra planner decision is needed after a hard limit. Final answer still validates citations and can abstain. Provider failures/incomplete outputs and invalid final citations still surface as errors, not as successful answers or false abstentions.
- Invalid/unsupported decisions, unknown chunk IDs, duplicate expansions and repeated search token sets are recoverable events. No unauthorized tool is executed. Blocked actions consume planner decisions, not successful tool calls; zero-result executed tools count as tools. No cross-source expansion. `unknown_chunk_id`, `duplicate_expansion`, `repeated_query_blocked`, `empty_query_blocked`, `invalid_decision` are trace outcomes. `MAX_NO_PROGRESS=2`: two consecutive actions without newly accepted chunks terminate research; an added chunk resets the counter. This is a heuristic, not a proof that useful evidence is exhausted.
- BM25 uses a set of normalized terms. Reordered/repeated tokens, case and punctuation changes with identical token sets are blocked. Different token sets remain allowed, even if semantically similar (no Jaccard threshold or embedding dependency).
- Planner instructions now prioritize missing facets (study, outcome, methods, limitations, quantities), record the target in `note`, and discourage consecutive adjacent expansions. Observation includes remaining evidence capacity and the complete bounded trace. This is prompt-guided decomposition, not an explicit coverage verifier or separate decomposition model. No gold facts enter prompts.
- Shared answer generator supports `answered`, `partially_answered`, `insufficient_evidence`. A supported negative conclusion can be `answered`; partial answers require at least one cited claim and a reason describing the gap; insufficient evidence requires zero claims and a reason. `reason_citation_ids` is a new structured array validated against retrieved evidence; metadata joins `citations`. Raw chunk-shaped IDs in non-answered reason prose are rejected. Legacy injected generator objects without this array still work, but the live JSON schema requires it. ID membership is not entailment validation; factual content in prose is not independently verified. Streamlit and CLI render partial claims and reason links.
- Evaluation JSONL includes `stop_reason`, `retrieved`, and `reason_citation_ids`. Existing Prometheus counters accept the new fixed stop/status labels and still exclude blocked actions from tool-call counts.

## Regression experiment (paid, opt in)

Reuse exactly the five synthesis questions from the previous experiment, preserving the old result file. Same model, top-k and planner budget. Keep the same corpus snapshot if possible.

```powershell
python scripts/eval_agent_vs_ask.py `
  --confirm-paid `
  --benchmark evaluation/benchmark_agent_synthesis.jsonl `
  --split test `
  --limit 5 `
  --output data/agent_synthesis_comparison_v2.jsonl
```

The generator changed for **both** endpoints, so compare new baseline vs new agent and old vs new within each mode; don't attribute all changes to agent orchestration. Check Q02 for finalization instead of a discarded search budget; Q14 for recovery from unknown/duplicate expansion; Q08 for meaningful supported claims and a properly qualified negative conclusion or partial result; Q11 for missing causal-methodology facets. Real model choices vary. No guarantee of 5/5 correct answers or lower latency. Assess required facts, entailment, partial and incorrect answers separately; source recall is only a proxy. The five test questions are now regression data, not a fresh holdout.

## Deferred

Adaptive routing, explicit subquestion coverage state, semantic near-duplicate detection, token/cost accounting, global deadline, PDF unit extraction repair, and fresh holdout evaluation. No live OpenAI or Docker run was performed in the patch preparation environment. Offline API tests use model doubles; test data is synthetic for the failure modes, not a scientific quality certification.
