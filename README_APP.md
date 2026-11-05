# Marine Evidence Finder — FastAPI + Streamlit MVP

This overlay builds a **local desktop demo** on top of the existing Marine Evidence Finder project. It reuses the existing `BM25Index`, word-safe chunker, provenance metadata, and OpenAI Responses API answer generator. **No Qdrant or new embeddings are required**.

## Install (PowerShell, from `marine-evidence-finder` root)

```powershell
Expand-Archive "$env:USERPROFILE\Downloads\marine_evidence_app_overlay.zip" -DestinationPath . -Force
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pip install -r requirements-answer.txt
python -m pip install -r requirements-app.txt
python -m pytest -q
```

Ensure `data/chunks/word_safe/chunks.jsonl` exists. The original 8 PDFs should be under `papers/` so **Open PDF** links work. If they are missing, the text search still works but links to those PDFs will return 404. Existing benchmark, fixed/word-safe chunks, E5/GTE indices and QA outputs are left untouched.

## Start the two processes

**Terminal A — API:**

```powershell
python -m uvicorn marine_evidence.api:app --host 127.0.0.1 --port 8000
```

Visit http://127.0.0.1:8000/docs for the interactive FastAPI API. Health: http://127.0.0.1:8000/health.

**Terminal B — UI** (in the same project folder, with `.venv` activated):

```powershell
python -m streamlit run streamlit_app.py
```

Your browser will show the Streamlit URL, generally http://localhost:8501.

## Demo workflow

1. See the eight benchmark papers in the sidebar.
2. Enter a question and select **Search passages (free)** to see BM25 results and open a source PDF at the cited page.
3. Select **Generate cited answer (OpenAI API)** and click **Generate answer** to make an explicit API call. It uses the `OPENAI_API_KEY` already stored in `.env` from Step 4. Answer citations are checked for valid chunk IDs, but entailment is **not automatically checked**.
4. Upload a **new text-based PDF** (max 25 MiB, max 100 pages). It is parsed into page records and 2000-char word-safe chunks with 300-char overlap. BM25 is rebuilt immediately so the next question can retrieve it. Duplicate documents are detected by SHA-256 and are not re-indexed.
5. Open a result's **PDF p.N** link in your browser. PDF viewer support for `#page=N` depends on the viewer/browser.
6. Optional: remove uploaded documents through the sidebar. The eight original benchmark papers cannot be deleted through the API.

## API routes

- `GET /health` — counts and retriever
- `GET /documents` — original + uploaded PDF metadata
- `POST /documents` — multipart form `file` (`.pdf` only), returns document id and counts
- `GET /documents/{source_id}/pdf` — original PDF, inline, with browser fragment `#page=N`
- `DELETE /documents/{source_id}` — removes **uploaded** document only
- `POST /search` — JSON `{ "question": "...", "top_k": 5, "distinct_pages": false }`
- `POST /ask` — same JSON plus optional `"model": "gpt-5-mini"`; paid LLM request

## File storage and privacy

- Original benchmark corpus: `data/chunks/word_safe/chunks.jsonl`, `papers/`. Never modified.
- Uploaded PDFs: `data/app/pdfs/U<hash>.pdf`
- Uploaded chunks: `data/app/chunks/U<hash>.jsonl`
- Upload manifest: `data/app/registry.json`
- `data/.gitignore` prevents committing uploaded data to Git (and your root `.gitignore` should already exclude `.env`, `papers/`, and generated data).
- **The app runs locally and has no authentication. Never expose the FastAPI server on `0.0.0.0` or to the public Internet without access controls, quotas and additional upload security.**
- **OpenAI API call:** only the question and top retrieved passages are sent to the configured model, not the full PDFs; passages can include excerpts from newly uploaded PDFs. Obtain permission before submitting private material. The `call_openai()` function uses `store=False`. Requests can incur OpenAI API charges.
- The system does not run arbitrary commands in a PDF; extracted content is treated as untrusted text. However, this is a teaching MVP, not a malware-hardened public document-processing service.

## Limitations

- OCR not implemented: image-only PDFs are rejected. Tables, reading order and multi-column extraction can be imperfect.
- BM25 is in-memory; index rebuilds on upload and process restart. The upload registry persists; uploaded texts remain searchable across restarts. **Run one API worker**: multiple workers would maintain independent caches and could race on the registry.
- Filename text is sanitized and stored under generated IDs; no uploaded filename is used as a server filesystem path.
- No autonomous LLM calls: only `/ask` and UI **Generate answer** invoke the paid API.
- Only chunk ID existence is mechanically verified; a citation may still fail to substantiate a particular claim. Manual review remains essential.
- A higher-level evaluation on 20 questions should be completed after the demo. The benchmark never enters the live retrieval index.

## Smoke test commands

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/search -ContentType 'application/json' -Body '{"question":"What did Blair report about humpback feeding?","top_k":5}'
```

If import fails, ensure `python -m pip install -e ".[dev]"` ran inside the same activated `.venv`.
