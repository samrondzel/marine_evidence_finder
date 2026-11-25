# Agentic RAG — final internal evaluation

## Design

Baseline BM25 top-12 vs bounded agent (initial top-4, maximum 12 evidence chunks, five planner decisions), using gpt-5-mini and the common generator after Sprint 4.4. Both support citation constraints and up to one answer repair. Original-question-first retrieval, budget-aware finalization, recoverable tool decisions, no-progress detection, request-local usage accounting and reviewed P05 unit corrections were introduced during development. The corpus and application were not altered by the CI patch.

## Frozen internal holdout (H01–H04, one run per mode)

| Question | Baseline status | Agent status | Baseline facts | Agent facts | Baseline seconds | Agent seconds | Baseline USD | Agent USD |
|---|---|---|---:|---:|---:|---:|---:|---:|
| H01 | answered | answered | 2/2 | 2/2 | 12.73 | 57.28 | 0.003145 | 0.01160750 |
| H02 | answered | answered | 2/2 | 2/2 | 18.51 | 120.02 | 0.00383225 | 0.01485015 |
| H03 | partially_answered | answered | 1/2 | 1/2 | 52.99 | 92.30 | 0.00631950 | 0.01614125 |
| H04 | insufficient_evidence | answered | 2/2 | 1/2 | 12.62 | 33.06 | 0.00341375 | 0.00556250 |
| Total | | | 7/8 | 6/8 | 96.85 | 302.66 | 0.01671050 | 0.04816140 |

Both modes returned four HTTP results without unknown citation IDs. Source recall on the three answerable questions was 100% in both. Baseline used 4 LLM calls and 33,690 tokens; agent used 21 calls and 79,666 tokens. The agent was about 3.13 times slower and 2.88 times as expensive for this run. The agent supplied additional context in H03 but missed the explicit P05 page 7 limitation; the stricter two-part gold rubric awards one of two points to both modes. H04 did not invent a numeric threshold but had the wrong status and omitted the model-based explanation. H02 recovered after an invalid planner decision; H04 stopped after two actions produced no new chunks. H01 spent all five planner decisions searching despite the cited final evidence being the first original retrieval hit.

## Interpretation

In earlier five-question synthesis development runs, the agent occasionally found important missing documents or passages (especially Q02, Q08, Q11, Q14), but the advantage was not stable across runs. Expanding static retrieval from 4 to 12 chunks improved coverage at relatively low latency. A later failed Q14 request demonstrated that costs are incurred even when the application rejects an invalid citation; Sprint 4.4 constrained citation IDs, retained the validator, and added a bounded repair. Successful Q14 and Q06 retests and corrected Q08 units are regression evidence, not a universal guarantee.

For a first release, prefer standard RAG top-12 and offer the research agent as an explicit experimental deep-research mode. This is an architectural recommendation, not a UI change made in this patch. Do not automatically route on model-reported answer status alone. The internal holdout uses new question formulations but overlaps previously observed facts; it is not independent external evidence of generalization. Required-fact scores are manual coverage judgments using the frozen rubric, not a full entailment audit of every scientific statement. Source-ID recall and citation membership do not establish scientific correctness. Costs are estimates from reported provider usage, not an invoice. Single-run latency and prompt-cache effects limit comparisons. Preserve the local benchmark JSONL and its recorded SHA-256 separately; do not commit private corpus data or generated logs.
