# Sprint 4.4 — Agent Hardening

Overlay for Sprint 4.3. No new runtime dependencies, database migrations, or automatic corpus mutations. Back up local modifications before expanding the ZIP. Test evidence: local reconstructed archive plus all overlays; deterministic fake provider, no paid requests or Docker execution here.

## Changes

- `answer_schema_for(hits)`: request-local copy of the Structured Outputs schema; restricts both `claims[].citation_ids` and `reason_citation_ids` to exact evidence IDs. Empty evidence uses zero-length citation arrays; normal workflows skip generation with no evidence. Local validation remains authoritative. Identity checking does not verify semantic entailment. The enum changes with evidence, which may affect provider schema/prompt caching.
- One fresh generation after invalid JSON or failed local answer validation, using the same question, evidence and constraints. No replay of untrusted invalid text. Provider errors, incomplete responses and empty output are not retried by this repair layer. A second invalid generation fails closed. At most two logical generator calls (SDK retries are separate). Both counted by the existing UsageLedger; the planner budget is unchanged.
- Both `/ask` and `/agent/ask` retain HTTP 502/503 and string `detail`, now with top-level `llm_usage` for caught AnswerError. The benchmark preserves usage, HTTP status and elapsed time in error rows, without guessing at usage for transport failures. Prometheus continues counting both successful and failed provider calls. Provider `completed` does not imply application success.
- Clarified status prompt: background is not partial coverage; an unsupported exact value is insufficient evidence. A supported negative conclusion to a yes/no component is a substantive answer. This is a prompt refinement, not a deterministic semantic classifier.
- Optional, separate `scripts/fix_p05_units.py`: on the supplied P05 PDF (SHA256 checked), PyMuPDF extracts `mPa` where the visible original says micro-Pascal. Visually reviewed all 12 whole-word occurrences in eight identified base chunks. Correct to NFKC-normalized `μPa` only for exact known original chunk text hashes; recognize already corrected hashes, reject changed text or unreviewed P05 occurrences. Dry run default, exclusive backup and atomic replacement on apply. No changes to other sources, IDs, page offsets or uploaded corpus. Does not repair PDF text layer, other PDFs, gold annotations, or intermediate `data/processed/pages.jsonl`; re-extracting/rechunking can reintroduce the defect. Re-run audit if corpus rebuilt. Other malformed characters/units require separate review.
- `--question-id` (repeatable) selects regression cases before limit. Candidate holdout: four newly authored questions H01–H04 with source quotes matched against the original PDFs; author is not independent and questions may overlap concepts with prior work. Review/freeze before evaluating, never use gold labels as prompts. Do not tune on it and then claim independent holdout performance. Truly independent evaluation should be independently annotated and withheld.

## Install and verify (PowerShell, project root)

```powershell
git status --short
Expand-Archive "$env:USERPROFILE\Downloads\marine_sprint4_4_agent_hardening.zip" -DestinationPath . -Force
python -m pytest -q
python scripts/smoke_agent.py
$cfg = @('-f','compose.yaml','-f','compose.postgres.yaml','-f','compose.metadata.yaml','-f','compose.jobs.yaml','-f','compose.observability.yaml')
docker compose @cfg config --services
docker compose @cfg up -d --build api ui
python scripts/smoke_observability.py
```

First retest on unchanged corpus to isolate code changes (paid):

```powershell
python scripts/eval_agent_vs_ask.py --confirm-paid --split test --mode agent --question-id Q14 --limit 1 --output data/agent_q14_hardening.jsonl
python scripts/eval_agent_vs_ask.py --confirm-paid --split dev --mode both --baseline-top-k 12 --question-id Q06 --limit 1 --output data/abstention_hardening.jsonl
```

Expected: no unavailable citation accepted; one repair max; if HTTP 502 persists, usage preserved in JSONL. For Q06 expect insufficient_evidence without invented threshold; a single live success does not establish robust classification. Check Grafana cost panels and Prometheus counters. Do not rerun large paid benchmark just to measure counters.

## Optional reviewed P05 correction (separate experiment)

```powershell
python scripts/fix_p05_units.py
# Only if dry run confirms 12 corrections (or already corrected):
docker compose @cfg stop api ui
python scripts/fix_p05_units.py --apply
docker compose @cfg up -d api ui
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

If the script reports a mismatch, do not bypass it. The original chunks.jsonl is backed up as `chunks.jsonl.before_p05_unit_fix`. To roll back, stop API/UI, restore the backup and start again. Keep before/after corpus fingerprints; earlier benchmarks used original corpus. The correction changes BM25 token statistics, so don't attribute changed retrieval solely to the hardening code.

Targeted paid Q08 after correction:

```powershell
python scripts/eval_agent_vs_ask.py --confirm-paid --split test --mode both --baseline-top-k 12 --question-id Q08 --limit 1 --output data/q08_corrected_units.jsonl
```

Manual review must check 96 dB re 1 μPa, 16 kHz third-octave, and no common threshold inferred; a model may still err even with corrected text.

## Experiment record (user-provided live runs, GPT-5 mini)

| Run | Baseline | Agent | Notes |
|---|---|---|---|
| Three dev cases, original-first | 2 answered + 1 abstention; 11.9 s avg | same statuses; 28.6 s avg | equal source recall for answerable cases |
| Five synthesis cases v1 | 2/5 answered; 80% source recall; 11.56 s avg | 2/5 answered; 100%; 48.59 s avg | budget and tool failures |
| Five synthesis cases v2 | top-4: 2/5 answered + 3 partial; 20.76 s avg | 5/5 answered; 57.53 s avg | status is not independent correctness |
| top-12 comparison | 4/5 answered + 1 partial; 100% recall; 26.07 s avg | compare with v2 above | equal maximum chunk budget, not equal token budget |
| cost run | 3 answered + 2 partial; 5 calls; $0.0232854 | 2 answered + 2 partial + 1 HTTP 502; 20 calls; $0.05195765 | costs from counters including failure, assuming only these requests since reset |

Cost-run Q14 error: unknown citation `P07:p0001:c0004`. Based on aggregate counters minus four reported successful rows, estimated failed request cost $0.0076045. Agent estimated cost 2.23x baseline over five attempts. Without cached input discount, same usage implies $0.029391 baseline vs $0.05403125 agent (1.84x). No measured invoice; SDK retries and unrelated concurrent requests may affect attribution. Five reused cases, one stochastic execution per configuration, no significance/independent evaluation; earlier 5/5 agent not reproduced. Source recall is document-level, not entailment. Agent can be useful on method-focused Q11, but default production should remain explicit baseline top-12 with opt-in Deep Research until stronger evaluation.

## Candidate holdout (only after review and freeze)

```powershell
python scripts/eval_agent_vs_ask.py --confirm-paid --benchmark evaluation/benchmark_agent_holdout_candidate.jsonl --split test --limit 4 --mode both --baseline-top-k 12 --output data/agent_holdout_candidate_results.jsonl
```

Manually score each required fact (0/1), count unsupported claims and unit errors, check quoted passages and requested facets, record status, errors, latency and cost including failures. Do not grade only by status. Candidate set is not external independent validation. No automatic router or semantic verifier is included.
