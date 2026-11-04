# Marine Evidence Finder — Word-safe Rechunk v1

## Purpose

Rebuild chunks **from existing** `data/processed/pages.jsonl` without touching the
original PDFs, `pages.jsonl`, `src/marine_evidence/chunk.py`, or the old BM25 baseline.

### Windows PowerShell (from project root)

Unzip `marine_word_safe_chunking_overlay.zip` into `marine-evidence-finder`.
The overlay adds `src/marine_evidence/chunk_word_safe.py` and
`tests/test_chunk_word_safe.py`. It does **not** overwrite previous source files.

```powershell
Expand-Archive "$env:USERPROFILE\Downloads\marine_word_safe_chunking_overlay.zip" -DestinationPath . -Force
python -m pip install -e ".[dev]"
python -m pytest -q
python -m marine_evidence.chunk_word_safe `
  --pages data/processed/pages.jsonl `
  --out-dir data/chunks/word_safe `
  --max-chars 2000 `
  --overlap-chars 300
```

Then point the **existing** BM25 evaluation at the newly generated chunks:

```powershell
python scripts/eval_bm25_dev.py `
  --chunks data/chunks/word_safe/chunks.jsonl `
  --benchmark evaluation/benchmark_v1.jsonl `
  --top-k 5 `
  --out-dir data/evaluation/bm25_dev_word_safe
```

The old `data/chunks/fixed/chunks.jsonl` stays untouched. If you deliberately want
the previous `fixed` path to contain the new chunks, pass
`--out-dir data/chunks/fixed` instead, **but you will overwrite that baseline**.

## Rules

- A chunk stays **within a single PDF page**; no page mixing.
- Maximum **2000 characters**, target **300 characters of overlap**.
- Cut points only at whitespace-delimited word beginnings; actual boundaries
  can be a little earlier than 2000 to avoid splitting a word.
- PDF soft line breaks inside a word (for example `adja-\ncent`) are kept **within
  a single chunk** whenever encountered near a boundary. The raw spelling is
  preserved in `text` so `start_char` and `end_char` still point exactly to the
  original page string.
- The old BM25 implementation **already removes line-wrap hyphenation for its
  indexing/tokenization only**. This new module intentionally does not alter
  source text; when we add semantic embeddings, we can apply the same
  text-only normalization to the model input, not to the citation text.
- A pathological unbroken token longer than 2000 characters raises an explicit
  error (rather than silently breaking a word or violating the character cap).
- Each chunk contains the fields expected by the previous BM25 implementation:
  `chunk_id`, `page_id`, `source_id`, `title`, `doi`, `filename`, `pdf_page`,
  `start_char`, `end_char`, `text`, `char_count`, `word_count`.

## What to check

The script writes `chunks.jsonl` plus `chunking_report.json`. Run the already
existing `scripts/check_dev_chunk_coverage.py` on the new path to check whether
all ground-truth snippets remain in at least one chunk:

```powershell
python scripts/check_dev_chunk_coverage.py --chunks data/chunks/word_safe/chunks.jsonl
```

**This is not Recall@5.** Re-run BM25 dev evaluation for a retrieval comparison.
Keep the held-out test split untouched during selection.
