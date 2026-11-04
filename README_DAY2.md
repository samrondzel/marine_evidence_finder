# Marine Evidence Finder — Day 2 / Step 2.1: PDF ingestion

## Goal
Build a deterministic, independently testable pipeline that extracts 1-based PDF pages and preserves source IDs. No LLM, vector DB, LangChain, or document chunks yet.

## Files added

- `src/marine_evidence/ingest.py`: deterministic PyMuPDF baseline, checksums, page metadata, JSONL output.
- `scripts/inspect_extraction.py`: inspect a specific page of extracted text.
- `tests/test_ingest.py`: automatic validation of basic extraction and fail-closed inputs.
- `pyproject.toml`: project dependencies and editable install.

## Setup (Windows PowerShell)

Run these **from the project root**, where `papers/` and `evaluation/` live:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q
python -m marine_evidence.ingest --papers-dir papers --manifest evaluation/papers_manifest.json --out-dir data/processed
python scripts/inspect_extraction.py --source P01 --page 3 --limit 2200
python scripts/inspect_extraction.py --source P02 --page 3 --limit 2200
```

### Optional developer-only extraction comparison

```powershell
python -m marine_evidence.ingest --reading-order sorted --papers-dir papers --manifest evaluation/papers_manifest.json --out-dir data/sorted_experiment
python scripts/check_dev_evidence.py --pages data/processed/pages.jsonl --benchmark evaluation/benchmark_v1.jsonl
python scripts/check_dev_evidence.py --pages data/sorted_experiment/pages.jsonl --benchmark evaluation/benchmark_v1.jsonl
```

The verifier reads **only** `dev` entries from the benchmark; don't inspect or tune on the `test` split. In our source corpus, native ordering preserved 21/21 dev quotes as contiguous substrings, while sorted ordering retained 11/21. This is a **text-contiguity diagnostic**, not a retrieval accuracy score, and one missing quote may result from PDF layout or normalization.

The PDFs must have **exactly the same names** as in `evaluation/papers_manifest.json`. The eight PDFs aren't included in this starter ZIP.

## Output contract

`data/processed/pages.jsonl` contains a JSON object per page:

```json
{
  "page_id": "P01:p0001",
  "source_id": "P01",
  "filename": "rsbl20180484.pdf",
  "title": "Dolphins simplify their vocal calls in response to increased ambient noise",
  "doi": "10.1098/rsbl.2018.0484",
  "pdf_page": 1,
  "text": "...",
  "char_count": 7000
}
```

`data/processed/ingestion_report.json` contains corpus totals and empty/short-page diagnostics.

## Why one record per page?

We need to trace any later retrieved chunk to a paper and page. Chunk boundaries may change many times during retrieval experiments, but PDF page numbering should be stable.

## Learning task / quality check

1. Open P01 page 3 in the original PDF and compare it with `inspect_extraction.py --source P01 --page 3`.
2. Repeat with P02 page 3 (multi-column article). Does the extracted reading order make sense?
3. Find at least one example where a figure caption, header, two-column text, or reference list is not in the expected order.
4. Explain **why position-based `sort=True` may be worse than the PDF native block order** for two-column scientific articles.

Do **not** remove page metadata or index `evaluation/benchmark_v1.jsonl`: gold answers are held out from retrieval.

## Caveat

This is deliberately the **baseline extractor**. It does not fully repair multi-column reading order, parse tables, do OCR, or strip reference sections. Those are measurable improvements to explore before chunking. All source text is preserved as extracted, not scientifically corrected.

## Next checkpoint

After you send the ingestion summary and a snippet from P02 page 3, we choose and test a chunking strategy (e.g. 350–500 tokens with overlap), define stable chunk IDs and validate citation traceability.
