# Marine Evidence Finder — Hybrid Search experiment (DEV only)

## Hypothesis

E5-small-v2 may be worse than BM25 on a small specialised PDF corpus because many generic introductory passages are semantically close to a general research question. We **do not assume** RRF will improve performance. The aim is to measure whether dense retrieval adds any evidence pages beyond BM25 on the same fixed dev set.

We combine *ranks* by weighted Reciprocal Rank Fusion (RRF), not raw scores. Raw BM25 values and cosine similarities have different scales. For chunk `c`:

`RRF(c) = w / (60 + rank_bm25(c)) + (1-w) / (60 + rank_e5(c))`

A chunk not returned by one of the two retrievers contributes zero from that retriever. This experimental baseline uses `w=0.75`, `candidate-k=40`, `top-k=5`. **These are starting parameters, not tuned optima.** If the hybrid is worse than BM25, retain BM25 as the baseline rather than claiming the hybrid is better.

## Install (PowerShell, project root)

```powershell
Expand-Archive "$env:USERPROFILE\Downloads\marine_hybrid_rrf_overlay.zip" -DestinationPath . -Force
python -m pytest -q
```

Existing word-safe chunks and E5 index remain unchanged.

## Compare three methods using the same DEV questions

```powershell
python -m scripts.compare_hybrid_dev `
  --chunks data/chunks/word_safe/chunks.jsonl `
  --index-dir data/index/e5_small_v2_word_safe `
  --benchmark evaluation/benchmark_v1.jsonl `
  --top-k 5 `
  --bm25-weight 0.75 `
  --out-dir data/evaluation/hybrid_dev_w075
```

This prints BM25, E5, and RRF source/page recall, per-question page recall, and page matches for Q13. Raw predictions and machine-readable metrics are also saved.

**Optional**: rerun with `--distinct-pages` to limit each source/page pair to a single result, then inspect how it changes evidence coverage. This is a different retrieval policy and must be reported as such.

## Inspect a specific question

```powershell
python -m marine_evidence.hybrid `
  --query "How does shipping noise interfere with feeding behaviour?" `
  --top-k 5 `
  --bm25-weight 0.75
```

For each hit, output includes its ranks in BM25 and E5. A high rank in both means the search methods agree; a missing rank means the passage was not in that method's top-40 pool.

## Check whether embeddings were truncated

```powershell
Get-Content data/index/e5_small_v2_word_safe/metadata.json -Raw |
  ConvertFrom-Json |
  Select-Object chunk_count,max_model_tokens,inputs_over_token_limit
```

If `inputs_over_token_limit > 0`, some passages were truncated *during embedding*, even though the original full text remains stored. That is worth fixing in a separate experiment. Avoid changing chunks and the index simultaneously while comparing methods.

## Interpretation

- BM25 strong on **lexical overlap** and named articles.
- E5 strong in principle on **semantic similarity**, but it can over-rank general introductions.
- RRF blends ranked lists; it is not guaranteed to improve evidence-page Recall@5.
- This benchmark scores the correct **PDF page**, not whether the retrieved chunk contains the exact evidence quote. Page recall is a useful coarse proxy, not a final faithfulness metric.
- Search uses **dev only**. Do not choose parameters using `test` until you freeze the experiment.

Next, if RRF fails to beat BM25: retain BM25 and test a stronger embedding model or a cross-encoder reranker using dev only. No need to add Qdrant or agents just to make the stack larger.
