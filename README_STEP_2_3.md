# Marine Evidence Finder — Step 2.3: BM25 Retrieval Baseline

A reproducible, **LLM-free** keyword-search baseline over the `chunks.jsonl` generated in Step 2.2. It uses no benchmark answers during indexing.

## 1. Install the overlay (Windows PowerShell)

Copy `marine_day2_bm25_overlay.zip` into Downloads. From the project root (`marine-evidence-finder`, where `pyproject.toml` is located):

```powershell
Expand-Archive "$env:USERPROFILE\Downloads\marine_day2_bm25_overlay.zip" -DestinationPath . -Force
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q
```

Expected after Step 2.2 + this overlay: `22 passed`.

## 2. Search the actual papers

```powershell
python -m marine_evidence.bm25 `
  --chunks data/chunks/fixed/chunks.jsonl `
  --query "Which changes in humpback whale foraging were linked to shipping noise?" `
  --top-k 5
```

A result has `source_id`, `pdf_page` (1-based PDF page), `chunk_id`, title, DOI, and an excerpt of **unmodified** PDF text. To avoid having multiple overlapping chunks from the same page dominate the results, optionally add `--distinct-pages`.

## 3. Evaluate on DEV only (not TEST)

```powershell
python scripts/eval_bm25_dev.py `
  --chunks data/chunks/fixed/chunks.jsonl `
  --benchmark evaluation/benchmark_v1.jsonl `
  --top-k 5
```

Output: `data/evaluation/bm25_dev/predictions_dev.jsonl` and `metrics_dev.json`. They contain only dev question IDs and retrieval results. Add `data/evaluation/` to your `.gitignore` to avoid committing generated diagnostics.

Optional exploratory run with distinct pages:

```powershell
python scripts/eval_bm25_dev.py --distinct-pages `
  --out-dir data/evaluation/bm25_dev_distinct
```

### Reproduced results (259 fixed chunks; default k1=1.5, b=0.75)

- Dev questions: 11; **8 answerable** scored for retrieval; **3 unsupported** not scored.
- Mean source recall@5: **1.000**.
- Mean directly supporting PDF-page recall@5: **0.938**.
- Q13 (ZoBell): found page 5 but missed page 2 in the top five (page recall 0.5).
- Page-diversity mode gave the same aggregate scores for this small dev set.

**What these numbers do NOT say:** They do not measure exact quotation retrieval, answer generation correctness, citation faithfulness, or abstention. Some questions name the author/paper, making source retrieval easier. The held-out test split must not be consulted to tune this baseline. To obtain more realistic estimates later, include questions without paper names and evaluate on new documents.

## 4. How classic BM25 works

For each query word `t`, BM25 gives each chunk a term score:

`IDF(t) * TF(t,d) * (k1 + 1) / (TF(t,d) + k1 * (1 - b + b * length(d)/avg_length))`

where `IDF(t) = log(1 + (N - df(t) + 0.5)/(df(t) + 0.5))` and N is the number of indexed chunks. This version counts unique query terms (a repeated question word does not get double weight).

- **TF**: repeated words matter, but saturate (10 repeats aren't 10x better than 1).
- **IDF**: rare words matter more than widespread words.
- **Length normalization**: long chunks are discounted relative to average corpus length.
- **Limitation**: BM25 only understands matching words, not synonyms, and the raw PDF text contains line-break hyphenation. We rejoin soft line-wrap hyphenation *for indexing only* so the original citation text and offsets stay unchanged.

## 5. Mini engineering review

1. Why might `whales` fail to match `cetaceans` in BM25?
2. If the same excerpt occurs in three overlapping chunks, what happens to the top-5?
3. Why is "found correct paper" a weaker metric than "found correct page"?
4. Why are unsupported questions excluded from retrieval recall, but retained for later abstention tests?
5. Why is a perfect dev score not proof of generalisation?

**Next:** semantic embeddings + vector retrieval, then side-by-side BM25-vs-semantic comparison on the *same dev questions*. Avoid peeking at `test` until the pipeline is frozen.
