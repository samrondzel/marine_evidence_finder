# Marine Evidence Finder — Benchmark v1

This is a **source-grounded QA evaluation dataset** assembled from the eight user-supplied research PDFs (see `papers_manifest.json`). It tests citation-grounded retrieval and answers about vessel noise and marine mammals.

## What's included

- `benchmark_v1.jsonl`: 20 versioned gold question-answer records; each includes source PDFs, 1-based PDF page references, short verifiable evidence excerpts, required facts and prohibited unsupported claims.
- `papers_manifest.json`: stable paper IDs, filenames, DOIs, SHA-256 checksums and PDF page counts.
- `ANNOTATED_QUESTIONS.md`: convenient, human-readable question/answer/evidence guide.
- `questions_overview.csv`: question index, types, split and source pages.
- `verify_dataset.py`: checks the file count, SHA-256, evidence spans and question types against the local PDFs.
- `retrieval_eval.py`: evaluates retrieval predictions, using PDF-page and paper-level recall.
- `predictions_template.jsonl`: placeholder for RAG retrieval predictions.
- `human_grading_template.csv`: per-question manual answer-accuracy, citation and hallucination ratings.

## Expected folder layout

```
marine-evidence-finder/
  papers/
    rsbl20180484.pdf
    41598_2017_Article_13252.pdf
    rsos190967.pdf
    rsbl20160005.pdf
    rspb20172314.pdf
    rspb20112429.pdf
    41598_2021_Article_96506.pdf
    sciadv.adf2987.pdf
  evaluation/
    benchmark_v1.jsonl
    papers_manifest.json
    ...
```

Your PDF filenames must match `papers_manifest.json`, or update their manifest filenames. The original PDFs are **not redistributed in the benchmark ZIP**; the user already has the eight PDFs and can place them under `papers/`.

## Run source validation

```powershell
python -m pip install pymupdf
python evaluation/verify_dataset.py --papers-dir ./papers
```

The script verifies: (1) manifest checksums, (2) source pages exist, (3) all extracted evidence excerpts really occur on the indicated pages, and (4) question and source IDs are internally consistent. Any mismatch is an error.

## Dataset split and methodology

There are 10 **fact** questions, 5 **synthesis** questions (including comparisons across papers), and 5 **abstention** questions. Each has `dev` or `test` split. Use `dev` when iterating on chunking, embedding models, BM25 etc., and report results on `test` after fixing parameters. Since answers are published in this deliverable, `test` is *not cryptographically blinded*; report this limitation and don't tune on it.

`evidence` contains **short directly verified excerpts**, not whole paper paragraphs. `pdf_page` is the page displayed by a PDF viewer, counting from 1. This is important because journal pagination sometimes differs.

### Important caveat: abstention cases

An `abstention` question asks for an **unjustified counterfactual or unreported numerical causal estimate**. The gold answer says the number is unsupported *in these eight PDFs*. Evidence tagged `scope` or `limitation` documents what the papers actually studied; **it does not logically prove that the claim is absent from all possible literature**. Do not generalize to the whole scientific field.

### Important caveat: citations

Gold citations are **PDF page level**, allowing a first-stage retrieval benchmark independent of your chunking strategy. If you later index multiple chunks from the same page, a hit on any chunk of that page counts as page coverage. This is a coarse metric: page recall does not itself ensure the retrieved chunk contains the exact answer. Consider quote-level span matching as a later upgrade.

### Recommended metrics

1. `Source Recall@5`: percentage of gold source PDFs covered among the first five retrieved chunks (**answerable questions only**). For synthesis questions, all required PDFs count toward the denominator. Abstention questions are excluded because their scope references are not targets that a correct answer must retrieve.
2. `Direct Evidence Page Recall@5`: percentage of gold PDF pages with direct supporting evidence covered among the first five retrieved chunks (answerable questions only). Context-only limitation/scope pages are not compulsory retrieval targets.
3. **Gold fact coverage:** manually grade each required factual element. Score 1 only for substantively correct information; score 0 for missing/incorrect.
4. **Unsupported claim rate:** manually record whether an answer contains forbidden unsupported claims or invented numerical values; report numerator/denominator.
5. **Abstention success rate:** for five unanswerable requests, answer must explicitly say the corpus does not support the requested figure or conclusion and avoid supplying a fabricated value.
6. **Citation accuracy:** human-check that a claimed source AND page actually support the assertion. Retrieval page match alone is not sufficient.

The automatic retrieval evaluator reports source/page recall; it **does not auto-grade faithfulness, uncertainty calibration or citation correctness**. Those need manual assessment or a separately validated evaluator.

## Example

```json
{"id":"Q01","retrieved":[{"source_id":"P01","pdf_page":1,"rank":1},{"source_id":"P02","pdf_page":3,"rank":2}]}
```

Run:

```powershell
python evaluation/retrieval_eval.py --predictions evaluation/predictions.jsonl --k 5
```

## Versioning / data leakage

Treat `benchmark_v1.jsonl` as **frozen** after review. If scientific corrections are needed, bump the benchmark version, document the reason and rerun every baseline. Avoid feeding gold answers directly into the retrieval index or generation context; only indexed publication text should be available to the RAG system.
