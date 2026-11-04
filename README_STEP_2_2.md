# Marine Evidence Finder — Day 2, Step 2.2: Chunking

## Purpose

Turn source-linked PDF pages into search chunks. Chunking is **not** an LLM operation; the central challenge is balancing context size and retrieval specificity without losing provenance. Each chunk stays inside **one PDF page** and has **exact character offsets** into `data/processed/pages.jsonl`.

## Install (from your marine-evidence-finder project root)

Unzip the overlay into the project root. It adds these files only:

- `src/marine_evidence/chunk.py` — deterministic chunker + CLI
- `scripts/check_dev_chunk_coverage.py` — development-only evidence coverage diagnostic
- `scripts/inspect_chunks.py` — inspect chunk text + offsets
- `tests/test_chunk.py` — tests
- `README_STEP_2_2.md` — this guide

Editable installation from Day 2 Step 2.1 remains valid. Run:

```powershell
python -m pytest -q
python -m marine_evidence.chunk --pages data/processed/pages.jsonl --out-dir data/chunks/fixed --strategy fixed --max-chars 1800 --overlap-chars 300
python scripts/inspect_chunks.py --source P02 --page 3 --limit 3
python scripts/check_dev_chunk_coverage.py --chunks data/chunks/fixed/chunks.jsonl
```

Compare an alternative **without touching test annotations**:

```powershell
python -m marine_evidence.chunk --out-dir data/chunks/boundary --strategy boundary --max-chars 1800 --overlap-chars 300
python scripts/check_dev_chunk_coverage.py --chunks data/chunks/boundary/chunks.jsonl
```

Try smaller and larger windows as experiments (e.g., 1200 and 2400 characters) and compare the number of chunks and dev coverage. **Do not** infer retrieval performance from this diagnostic. We will implement BM25 and measure Recall@5 on ranked chunks at the next stage.

## Output contract

Every JSONL row contains `chunk_id`, `page_id`, `source_id`, `title`, `doi`, `filename`, `pdf_page`, `start_char`, `end_char`, `text`, `char_count`, `word_count`. Character offsets refer to the page's exact extracted Python Unicode string (not byte offsets). They allow back-references without ambiguous matching.

**Important:** `--max-chars 1800` is a character budget, NOT a tokenizer budget. You can add model-specific token counting later.

## Why overlap?

Suppose the passage "dolphins raised whistle frequencies" sits across a chunk boundary. Without overlap, neither chunk may contain the full sentence. A 300-character overlap helps preserve boundary evidence, but increases the number of near-duplicate chunks and indexing cost. We don't know the best value without retrieval experiments.

## Why no chunks spanning two PDF pages?

It would complicate citation, because one search hit might support statements using page 3 and page 4 simultaneously. Keeping a chunk within a page makes click-through citations reproducible, at the cost of missing cross-page context. This is an explicit MVP tradeoff.

## Engineering checkpoint

Explain (1) what the `start_char`/`end_char` offsets guarantee, (2) why overlap might help **and** hurt retrieval, and (3) why page-level citation becomes unreliable if a single chunk spans multiple PDF pages without multi-page metadata.

After this checkpoint we implement sparse BM25 baseline, then compare semantic retrieval and hybrid ranking on the frozen benchmark.
