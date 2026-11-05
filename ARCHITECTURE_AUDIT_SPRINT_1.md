# Marine Evidence Finder — Hackathon #2, Sprint 1: Architecture Audit

**Snapshot:** 2026-11-05, inspected the user's uploaded project archive. 76 existing tests passed before changes. The provided project contains 8 reference PDF entries, 238 word-safe BM25 chunks and an upload registry. Original PDFs and user uploads are NOT included in this patch.

## 1. Current request path

```text
Streamlit (streamlit_app.py)
  | HTTP requests
  v
FastAPI (src/marine_evidence/api.py)
  |---- GET /health, /documents, /documents/{id}/pdf
  |---- POST /documents -> CorpusStore.upload_pdf()
  |                       -> PyMuPDF extraction -> word-safe chunking
  |                       -> JSONL/PDF disk storage -> BM25 index rebuild
  |---- DELETE /documents/{id} -> registry + file updates -> BM25 index rebuild
  |---- POST /search -> CorpusStore.search() -> BM25Index
  `---- POST /ask -> answer_question() -> BM25Index -> OpenAI Responses API
```

**Data:** `data/chunks/word_safe/chunks.jsonl` (fixed benchmark corpus), `papers/` (original PDFs), `data/app/registry.json` + `data/app/pdfs/` + `data/app/chunks/` (mutable uploads). For Q&A the server only validates that citation IDs exist in the retrieved chunks; scientific entailment requires separate evaluation.

## 2. What is already working

- Testable pure-ish retrieval and chunking modules (`bm25.py`, `chunk_word_safe.py`).
- Reproducible baseline and comparison benchmarks (BM25 vs E5 vs GTE).
- PDF validation, upload limits, generated source IDs, duplicate detection by SHA-256.
- FastAPI application factory `create_app()` supporting dependency injection in tests.
- 76 pre-existing tests green on the inspected snapshot.

## 3. Prioritized architecture risks

| Priority | Observation in code | Why it matters | Planned response |
| --- | --- | --- | --- |
| P0 for public deployment | API has no authentication, quotas or rate limits; `/ask` can call a paid model. | Unauthorized access and unbounded API costs. | **Keep localhost only**. Add auth and per-user quotas before any public cloud release. |
| P1 | `CorpusStore` combines PDF extraction, JSON registry persistence, file lifecycle, and a mutable in-memory BM25 index. | Difficult to replace the registry with a DB or to test storage independently. | Extract repository interface and database implementation during PostgreSQL sprint, preserving `CorpusStore` public behaviour. |
| P1 | Registry/files updated under `threading.RLock()` only. | Multi-process workers do not share a lock or BM25 state; concurrent writes can race. | Single worker until shared DB + synchronization strategy exist. |
| P1 | Uploaded PDFs and chunks are on local disk. Registry requires files to exist at startup. | Destroying an ephemeral container loses documents or prevents startup. | Persistent Docker volume and DB migrations. |
| P1 | Startup paths depend on process working directory (`Path.cwd()`). | Fragile under Docker, IDEs and background process managers. | **Fixed in Sprint 1** with environment-driven paths. |
| P2 | Application runtime dependencies split over requirements files; only PyMuPDF is in the main `pyproject.toml`. | Builds may accidentally omit dependencies; reproducibility limited. | Centralize extras/lock strategy in Docker stage. |
| P2 | Streamlit uses the same API URL for HTTP requests and browser PDF links. | `http://api:8000` is reachable *inside* a container network, not from the user's browser. | Split internal API URL from public browser URL during Docker stage. |
| P2 | Health endpoint included collection counts but no dedicated liveness/readiness paths. | Poor orchestration diagnostics. | **Fixed in Sprint 1**. DB readiness check comes with DB integration. |
| P2 | Upload PDF is parsed synchronously in a thread and index rebuilt for all documents. | Latency/CPU cost grows with corpus; no job status or queue. | Background jobs and monitoring in later hackathon, not this sprint. |

## 4. Sprint 1 patch (this ZIP)

1. `src/marine_evidence/config.py`: immutable `AppPaths` resolving file locations from `MARINE_PROJECT_ROOT`, `MARINE_BASE_CHUNKS_PATH`, `MARINE_BASE_PAPERS_DIR`, `MARINE_UPLOADS_DIR`, `MARINE_BASE_MANIFEST_PATH`.
2. `src/marine_evidence/api.py`: `create_app()` now gets its paths through `AppPaths` (while existing injected `store` behaviour remains intact). Typed response contracts on `/health` and `/search` appear in OpenAPI.
3. New `GET /health/live`: static process liveness; no disk/database/API request.
4. New `GET /health/ready`: verifies initialized collection and its index. **Does not yet check PostgreSQL**; that must be added when PostgreSQL exists.
5. Six new tests cover environment/path overrides, API readiness and OpenAPI response schema.

**Validation:** 82/82 tests passed on Python 3.13 in the review environment. With clean uploads directory and archived benchmark chunks, `GET /health` returned 8 documents and 238 chunks; `POST /search` returned a P04 p.1 hit for a humpback foraging question. No paid LLM request was used.

## 5. Target architecture for Hackathon #2

```text
Streamlit frontend --> FastAPI routes / typed contracts
                         |----> Search / Answer service ----> BM25 / LLM API
                         |
                         `----> Document service
                                  |----> document/chunk repository (PostgreSQL)
                                  `----> blob repository (persistent PDF volume)

Docker Compose: api + ui + postgres, healthchecks, persistent volumes.
GitHub Actions: lint/tests + integration tests + build smoke tests.
```

DB design sketch (to review before implementation):

- `documents`: `source_id` PK, `sha256` UNIQUE, `filename`, `title`, `doi`, `page_count`, `uploaded`, `created_at`.
- `chunks`: `chunk_id` PK, `source_id` FK, `pdf_page`, `start_char`, `end_char`, `text`; index on `source_id, pdf_page`.
- Keep PDF binary blobs on a mounted volume; database stores IDs/metadata and checksums. Have a consistent upload transaction or staging+compensation so database never references a nonexistent PDF.
- Build BM25 snapshot from DB chunks on startup and after a committed mutation, until the collection is large enough to justify an external search engine.
- Alembic migrations are versioned and run as a separate controlled step.

## 6. Definition of done for next sprint

- `docker compose up --build` launches API and UI locally; browser links point to browser-accessible API host, not container hostname.
- App works after restart and after `docker compose down` / `up` (without `-v`), preserving uploaded PDF and searchable chunks.
- Healthchecks prove API and PostgreSQL availability, not just process existence.
- Local `.env` secrets are not copied into images or committed.
- Existing test suite remains green; integration smoke test queries `/health`, `/search`, uploads a synthetic PDF, checks retrieval, then deletes it.
- PostgreSQL migration and CI should follow after the Docker baseline is stable. Do not deploy publicly with current unauthenticated endpoints.

## 7. Mini interview checkpoint

**Question:** Why is a `threading.RLock` insufficient to protect our upload registry if we run Uvicorn with `--workers 4`?

**Expected direction:** An in-process lock protects only threads in one process, not separate worker processes. Each worker would keep its own `CorpusStore` and BM25 snapshot. A shared transactional store plus process-level refresh/consistency strategy is required.
