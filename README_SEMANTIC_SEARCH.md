# Marine Evidence Finder — Semantic Search (E5-small-v2)

This overlay adds dense retrieval **without replacing BM25 or changing the original PDF/citation text**.

## 1. Installation (PowerShell, from the project root)

Extract ZIP **into `marine-evidence-finder`**, alongside `src/`, `scripts/`, `tests/`, and `pyproject.toml`.

```powershell
Expand-Archive "$env:USERPROFILE\Downloads\marine_semantic_search_overlay.zip" -DestinationPath . -Force
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pip install -r requirements-semantic.txt
python -m pytest -q
```

Installation of `sentence-transformers` includes PyTorch and may take a little time. The embedding model is downloaded from Hugging Face on first use; later it is cached. No paid API or GPU required. An internet connection is needed for the initial download.

## 2. Verify your current word-safe chunks

```powershell
Test-Path data/chunks/word_safe/chunks.jsonl
```

Expected `True`. If not, regenerate from the existing extracted pages (no PDF re-ingestion):

```powershell
python -m marine_evidence.chunk_word_safe --pages data/processed/pages.jsonl --out-dir data/chunks/word_safe --max-chars 2000 --overlap-chars 300
```

## 3. Generate and cache the dense index (once per chunk/model version)

```powershell
python -m marine_evidence.semantic build `
  --chunks data/chunks/word_safe/chunks.jsonl `
  --index-dir data/index/e5_small_v2_word_safe
```

This creates `vectors.npy` and `metadata.json`. It saves the model name, chunk IDs, and SHA-256 hash of the exact `chunks.jsonl`. If you rebuild the chunks, regenerate the index: otherwise it refuses to search against mismatched data.

Model: [`intfloat/e5-small-v2`](https://huggingface.co/intfloat/e5-small-v2) (English only; max 512 tokens). Every chunk receives a `passage: ` prefix, every question `query: `. Both vectors are L2-normalized and ranked with dot product (= cosine). Word wrapping like `adja-\ncent` is normalized for embedding only, preserving raw text for citations. The CLI reports any passages that exceed the model's token limit; those may be truncated for embedding even though the full original chunk remains in the citation text. No benchmark answers are embedded.

**Why no Qdrant or FAISS yet?** About 239 chunks × 384 dimensions × 4 bytes ~= 0.35 MB. Exact exhaustive dot product in NumPy is enough and has no approximate-index confound. We'll use a vector database if the corpus grows.

## 4. Run one semantic search

```powershell
python -m marine_evidence.semantic search `
  --chunks data/chunks/word_safe/chunks.jsonl `
  --index-dir data/index/e5_small_v2_word_safe `
  --query "Which changes in humpback whale foraging were linked to shipping noise?" `
  --top-k 5
```

Try `--distinct-pages` to ensure one hit per PDF page. Returned results preserve `source_id`, page number and source text.

## 5. Compare *both retrievers on the same chunks and the same DEV questions*

```powershell
python -m scripts.compare_retrievers_dev `
  --chunks data/chunks/word_safe/chunks.jsonl `
  --index-dir data/index/e5_small_v2_word_safe `
  --benchmark evaluation/benchmark_v1.jsonl `
  --top-k 5
```

This writes `data/evaluation/compare_dev_e5_word_safe/metrics_dev.json` and separate predictions for both methods. **Q13** is printed separately. What matters is not only the mean metric, but which question/page each method gains or loses.

Do not tune on the held-out `test` split. `Source Recall@5` and `Direct Evidence Page Recall@5` are page-level proxies: **they do not prove the exact answer passage was found**, and they do not measure generation correctness or hallucination.

## 6. Engineering reflection

1. BM25 matches keywords; E5 compares learned vector representations. Which can retrieve a scientific passage about *prey capture* for a question about *feeding disruption* without exact words?
2. When is BM25 likely to beat dense retrieval (numbers, DOI codes, proper names)?
3. Would a larger chunk help recall or obscure the exact evidence? Compare using `dev` only.
4. If Q13 is still missed, does that show a failure of embeddings, question design, passage granularity, or the top-5 budget?

### Troubleshooting

- `ModuleNotFoundError: sentence_transformers`: use `python -m pip install -r requirements-semantic.txt` inside your `.venv`.
- Model download fails: internet/Hugging Face access is needed once, then cached.
- `STALE INDEX`: rerun `semantic build` for the new `chunks.jsonl`.
- `403` / gated model error: check you used the public `intfloat/e5-small-v2` model name.
- A CPU is sufficient, but the first model download/embedding pass may take several minutes.
