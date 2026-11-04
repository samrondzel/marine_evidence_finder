# Marine Evidence Finder — Step 4: Evidence-level evaluation + grounded answers

This ZIP is an **overlay** for the existing Marine Evidence Finder project. It does not replace the eight PDFs, `pages.jsonl`, `chunks.jsonl`, BM25, E5, GTE, or the frozen benchmark.

## What changed

- `src/marine_evidence/evidence_eval.py`: **DEV-only** quote-level BM25 retrieval evaluation. Counts a direct `support` quote only if its normalized literal text is found in one of the top-k returned **chunks**, not merely on the same PDF page.
- `src/marine_evidence/answer.py`: retrieve 5 BM25 passages, pass only those passages to an OpenAI Responses API model, demand structured JSON and references to retrieved chunk IDs; validate citations against actual retrieved chunks. Handles unsupported questions by allowing `insufficient_evidence`.
- `scripts/run_qa_dev.py`: explicit, limited, **opt-in paid** DEV answer generation; emits JSONL predictions and a human evaluation CSV. Default mode makes **zero** API calls.
- `requirements-answer.txt`, `.env.example`, `tests/`.

**Critical distinction:** validated citation IDs mean the source exists in the retrieved context. They do NOT automatically prove the cited passage logically supports the claim. Manual scientific checking is still required. Neither the retriever nor the LLM is given gold answers.

## Install on Windows PowerShell

From the project root containing `pyproject.toml` and `data/chunks/word_safe/chunks.jsonl`:

```powershell
Expand-Archive "$env:USERPROFILE\Downloads\marine_evidence_step4_overlay.zip" -DestinationPath . -Force
python -m pip install -e ".[dev]"
python -m pytest -q
```

Expected with all previous overlays: `63 passed` (this build). Your previous files should remain untouched.

## 1. Measure actual passage evidence, no API key needed

```powershell
python -m marine_evidence.evidence_eval `
  --chunks data/chunks/word_safe/chunks.jsonl `
  --benchmark evaluation/benchmark_v1.jsonl `
  --top-k 5
```

Verified on the original corpus as supplied in this conversation:

```text
DEV only | 238 chunks | 8 answerable questions | top-5
Quote recall (micro): 0.909 (10/11)
Quote recall (macro): 0.938
Any support quote in top-5: 1.000
Quote coverage across all chunks (oracle): 1.000
Q07: 1/2 quotes; all other answerable dev questions: full quote coverage at top-5
```

Metrics are stored in `data/evaluation/evidence_dev/metrics_dev.json`.

**Metric definitions:**
- Micro quote recall = fraction of all annotated `support` quotes found verbatim (whitespace-normalized) within top-k chunks.
- Macro quote recall = mean quote recall across answerable DEV questions.
- Any quote hit = fraction of answerable DEV questions with >=1 annotated support quote retrieved.
- Oracle quote coverage = percentage of gold support quotes found in at least one chunk anywhere (unranked).

Exact substring matching is conservative; a paraphrase or a shorter yet sufficient supporting passage may be unfairly counted as missing. It is not an automated truthfulness grade.

## 2. Preview BM25 without calling LLM

```powershell
python -m marine_evidence.answer `
  --query "How did shipping noise change humpback whale foraging?" `
  --preview-only
```

## 3. Enable answer generation (paid OpenAI API)

Install dependencies:

```powershell
python -m pip install -r requirements-answer.txt
Copy-Item .env.example .env
```

Edit `.env` locally, enter your own `OPENAI_API_KEY`, and **do not commit it to Git**. Check `.gitignore` contains `.env` and `data/evaluation/`. Your ChatGPT subscription and OpenAI API credits are separate. Only **retrieved excerpts** (and the question) are sent to the model, not the full PDFs or the benchmark. You must explicitly decide whether that is acceptable for each corpus. The script uses `store=False`; review your account's API data handling settings.

Run one question:

```powershell
python -m marine_evidence.answer `
  --query "In Blair et al. (2016), what changes in foraging were associated with ship noise?" `
  --model gpt-5-mini `
  --top-k 5 `
  --out data/evaluation/one_answer.json
```

Try an unsupported question (correct behaviour: explain that the corpus does not establish an exact number):

```powershell
python -m marine_evidence.answer `
  --query "What is the exact universal noise threshold above which every humpback whale becomes completely unable to communicate?" `
  --model gpt-5-mini
```

**Avoid relying on confidence or cosine score** as an abstention threshold: the model must inspect retrieved evidence and declare uncertainty when appropriate. A good retrieved source does not guarantee that it supports the requested conclusion.

The model is configurable with `--model`. Default `gpt-5-mini` is only a starting choice; availability, cost, and compatibility depend on your API account. The code uses the modern **Responses API** with a strict JSON schema and `store=False`.

## 4. Generate pilot answers for manual evaluation

First show which DEV questions would be submitted **without spending API credits**:

```powershell
python -m scripts.run_qa_dev --limit 3
```

Then explicitly run at most three paid calls:

```powershell
python -m scripts.run_qa_dev `
  --limit 3 `
  --model gpt-5-mini `
  --execute
```

Files created:

- `data/evaluation/qa_dev/answers_dev.jsonl` — structured predictions, verified citation IDs, retrieval ranks.
- `data/evaluation/qa_dev/manual_review_dev.csv` — DEV-only gold answers and fields to grade: fact coverage, citation accuracy, unsupported claims, and abstention.

The first three DEV questions include an abstention case (Q06). `--limit 3` prevents accidentally running all 11 paid requests. For more questions, deliberately increase this number.

## How to manually grade

For **answerable** questions, compare model claims against the *retrieved chunk text* and the PDF. Check each source ID and PDF page, whether each fact follows from that specific quote, and whether numerical details, modelling/measurement, and causal language are correct. Mark unsupported assertions even if the citation exists.

For **abstention** questions, check if the model declines to invent unsupported figures and explains what data is missing. Avoid treating all unknown requests as a generic refusal; the model should still describe justified partial findings where possible.

## Known limitations and next steps

- 8 answerable questions on DEV is small. Perfect `Any quote hit` can easily overstate reliability. Do not tune against `test` before choosing a final pipeline.
- Exact quote matching cannot handle semantic paraphrases or evidence spread across multiple chunks.
- Model output is formatted and citation IDs are validated, but **not logically verified**. This is why the manual review CSV exists.
- Failure to find evidence is a retrieval problem; failure to use available evidence is a generation problem. Diagnose them separately.
- We have not yet built a Streamlit/FastAPI UI. After manual evaluation, add a UI and preserve links to original PDF page numbers.
- The model may be subject to usage charges and needs network access. Local tests use fake API responses and do not incur charges.
