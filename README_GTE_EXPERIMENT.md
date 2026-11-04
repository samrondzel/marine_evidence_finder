# Marine Evidence Finder — Step 3.2: GTE ModernBERT experiment

**Goal:** compare BM25, the existing E5-small-v2 index, and `Alibaba-NLP/gte-modernbert-base` on the **same** 238 `word_safe` chunks and the same **dev** benchmark. No PDF re-ingestion, no re-chunking, no changes to the benchmark, no need for a vector database.

## Why this overlay changes `semantic.py`

The existing implementation adds `passage: ` and `query: ` prefixes, **as required by E5**. GTE ModernBERT is different: the official model examples use **unprefixed passages and queries**. Merely changing `--model` in the old script would produce an invalid comparison.

The revised module reads each index's saved model identity and applies the correct prefix rules:

- `intfloat/e5-small-v2`: `passage: ...` and `query: ...` (the **existing** index continues to work).
- `Alibaba-NLP/gte-modernbert-base`: the text without either prefix.

Both use cosine similarity over unit-length vectors. GTE is a **768-dimensional**, **8192-token** model. E5-small-v2 has **384 dimensions** and a 512-token window. The test checks whether inputs exceed each model's actual tokenizer limit, not a character-count estimate. GTE is larger, so CPU indexing will take longer. There is no benefit to installing `flash_attn` on Windows for this CPU baseline.

Model card: https://huggingface.co/Alibaba-NLP/gte-modernbert-base

## Installation: Windows PowerShell

Run from the directory containing `pyproject.toml`, `src/`, `evaluation/`, and `data/`:

```powershell
Expand-Archive "$env:USERPROFILE\Downloads\marine_gte_modernbert_overlay.zip" -DestinationPath . -Force
python -m pip install -r requirements-gte.txt
python -m pytest -q
```

This archive replaces only `src/marine_evidence/semantic.py` and adds a few scripts/tests. It does **not** overwrite `chunks.jsonl` or the old E5 index. `transformers>=4.48,<5` is specified because native ModernBERT support begins with 4.48. No `trust_remote_code=True` is used.

## Build the GTE index (one time)

```powershell
python -m marine_evidence.semantic build `
  --chunks data/chunks/word_safe/chunks.jsonl `
  --index-dir data/index/gte_modernbert_word_safe `
  --model Alibaba-NLP/gte-modernbert-base `
  --batch-size 4
```

The first invocation downloads the model from Hugging Face (it is larger than E5). GPU is **not** required; the script uses CPU. For very limited RAM, try `--batch-size 1`.

**Check the tokenizer truncation report:**

```powershell
Get-Content data/index/gte_modernbert_word_safe/metadata.json -Raw |
  ConvertFrom-Json |
  Select-Object model_name,chunk_count,embedding_dimension,max_model_tokens,inputs_over_token_limit,document_prefix,query_prefix
```

Expect the model name to be GTE, the embedding dimension to be 768, and both prefix fields to be empty. The actual number exceeding the token limit will be reported by the script; on 2000-character chunks we expect none, but don't assume it without checking. The original E5 index should remain at `data/index/e5_small_v2_word_safe`.

## Inspect a single search

```powershell
python -m marine_evidence.semantic search `
  --chunks data/chunks/word_safe/chunks.jsonl `
  --index-dir data/index/gte_modernbert_word_safe `
  --query "How does shipping noise interfere with feeding behaviour?" `
  --top-k 5
```

## Fair head-to-head evaluation — DEV only

```powershell
python -m scripts.compare_models_dev `
  --chunks data/chunks/word_safe/chunks.jsonl `
  --e5-index data/index/e5_small_v2_word_safe `
  --gte-index data/index/gte_modernbert_word_safe `
  --benchmark evaluation/benchmark_v1.jsonl `
  --top-k 5
```

Reports: `data/evaluation/compare_dev_gte/metrics_dev.json` and three per-model `predictions_..._dev.jsonl` files. No `test` records are scored or emitted.

We report **two different page metrics** rather than silently changing historical definitions:

- `LegacyPageRecall`: matches the original evaluator, which counts both `support` *and* `method` evidence pages (but not `scope` / `limitation`). This allows direct comparison with earlier numbers: BM25 ~= 0.938, E5 ~= 0.562.
- `SupportOnlyPageRecall`: counts only pages whose evidence annotation role is `support`. **In our current dev data, BM25 = 1.000 on this metric.** That means it finds at least one chunk from every gold support page; it does **not** prove that the returned chunk contains the exact supporting sentence.

**Q13:** P07 page 5 contains the numerical answer, while P07 page 2 provides method context. The old 0.5 page score should not be read as BM25 missing the numerical evidence. The script also prints the rank of both pages in each model's first 30 hits for diagnosis.

### How to interpret outcomes

GTE might beat E5 but still lose to BM25. Or it might match BM25 on `SupportOnlyPageRecall` but differ in exact-passage quality. We have not run the pretrained GTE model in this build environment, so **no GTE accuracy numbers have been measured here**. The code and evaluation plumbing were tested offline using deterministic fake encoders.

Do not tune against `test`. We should evaluate exact evidence-chunk/quote retrieval and answer faithfulness separately before choosing the final retrieval stack. With such a small, topic-specific dev set and author-name clues, even perfect recall is not proof of generalization.

## Troubleshooting

- `ImportError` involving ModernBERT: rerun `python -m pip install -r requirements-gte.txt` and check `python -m pip show transformers sentence-transformers`.
- CUDA / memory error: model is already forced to CPU; try `--batch-size 1`.
- Hugging Face warning about unauthenticated requests: an `HF_TOKEN` is optional for public model downloads (the warning itself is harmless).
- `STALE INDEX`: the hash of `chunks.jsonl` differs. Rebuild the **corresponding** index from exactly the file being tested; do not reuse a vector index for a different corpus.
- If the model exceeds the available RAM or download is interrupted, keep BM25 as the working baseline; do not replace its results with guessed GTE metrics.
