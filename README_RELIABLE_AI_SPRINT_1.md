# Marine Evidence Finder — Reliable AI Systems, Mini-Hackathon #3 / Sprint 1

**Target:** an actual vertical slice of asynchronous PDF ingestion. This is NOT the full reliable-job system yet: retries, stale-running recovery and fault-injection are Sprint 2–4 work. No new retrieval model, pgvector or RAG changes.

## How it works

```text
Streamlit / curl
    |
    | POST /ingestion-jobs (PDF bytes, 25 MiB max)
    v
FastAPI: validate filename/header; write staging/<job_id>.pdf
    | (1) commit job status="queued" into PostgreSQL
    | (2) enqueue job_id into Redis using RQ
    v
HTTP 202 {job_id, status, status_url} (no PDF extraction in HTTP request)
    |
    | Redis queue "marine-ingest"
    v
RQ worker, separate Docker container
    | claim job: queued -> running (PostgreSQL conditional UPDATE)
    | read staging PDF from shared bind mount
    | call existing CorpusStore.upload_pdf:
    |    validate + extract + chunk + save PDF/chunks + INSERT document metadata
    | mark job succeeded with source_id (or failed on an ordinary exception)
    v
GET /ingestion-jobs/{job_id} -> queued/running/succeeded/failed
    |
    v
FastAPI /documents, /search, /ask, /PDF read paths:
    compare PostgreSQL document IDs+SHA-256 with in-memory CorpusStore
    if changed: load new JSONL + atomically swap BM25 index
```

**Why the final reload matters:** the API and worker are separate *processes*. Redis and PostgreSQL do not magically update an in-memory BM25 index inside the API. Our first version polls PostgreSQL on API reads and rebuilds BM25 only when document membership changes. Fine for a tiny teaching corpus; this is not the scalable final solution.

### What changes in the code

- `src/marine_evidence/db_models.py`, `migrations/versions/0002_ingestion_jobs.py`: versioned `ingestion_jobs` table. The existing `uploaded_documents` schema is retained.
- `src/marine_evidence/ingestion_job_repository.py`: persistent job state (`queued`, `running`, `succeeded`, `failed`).
- `src/marine_evidence/ingestion_jobs.py`: RQ worker function using the **existing** PDF processing pipeline.
- `src/marine_evidence/api.py`: new endpoints and opt-in Redis queue initialization.
- `src/marine_evidence/corpus_store.py`: refresh in-memory BM25 after a different process commits document metadata.
- `compose.jobs.yaml`, `Dockerfile.jobs`, `requirements-jobs.txt`: Redis + RQ worker and API build with queue dependencies.
- `streamlit_app.py`: with `MARINE_ASYNC_INGESTION=1`, upload submits a job and displays its status; click **Refresh ingestion status** while processing.
- `scripts/smoke_ingestion_jobs.py`: uploads a real PDF via HTTP and polls until finished.
- `tests/test_ingestion_jobs.py`: isolated tests without network, including API enqueue, worker processing, failure and Alembic migration.
- `tests/test_postgres_live.py`: schema assertion updated from Alembic revision 0001 to **0002**.

## Before installing

Work from your **current working project** with all previous backend/PostgreSQL sprints installed. **Do not** extract this ZIP into a bare clone without those updates. Commit your work and back up `data/app` and the PostgreSQL named volume. Do not run `docker compose down -v` on real data.

```powershell
# From the repo root:
git status --short
git switch -c feature/reliable-ai-systems
Expand-Archive `
  "$env:USERPROFILE\Downloads\marine_reliable_ai_sprint1_overlay.zip" `
  -DestinationPath . -Force
python -m pip install -r requirements-db.txt
python -m pytest -q
```

On the reconstructed previous sprint, **109 passed, 5 skipped** (the five skipped ones require the opt-in test PostgreSQL). Existing tests must continue passing. The new test suite does not require Redis or RQ to be installed locally because it injects a fake queue; real Redis/RQ run in Docker.

## Apply the *new* Alembic migration, then run the stack

Compose requires **all four files** in this order: `compose.yaml`, `compose.postgres.yaml`, `compose.metadata.yaml`, `compose.jobs.yaml`.

```powershell
$cfg = @('-f', 'compose.yaml', '-f', 'compose.postgres.yaml', '-f', 'compose.metadata.yaml', '-f', 'compose.jobs.yaml')

docker compose @cfg config --quiet

docker compose @cfg build db-migrate
docker compose @cfg --profile tools run --rm db-migrate

docker compose @cfg --profile tools run --rm db-migrate alembic -c alembic.ini current
```

The current revision must be **`0002_ingestion_jobs (head)`**. Migration #2 adds the job table but keeps your existing `uploaded_documents` records. Do not roll back or wipe your database.

Now start the queue and re-build the API (needs RQ+Redis dependencies) and worker:

```powershell
docker compose @cfg up -d --build api ui worker redis
docker compose @cfg ps
docker compose @cfg logs --tail 60 worker
```

Redis runs on Docker's **internal** network, not a published host port. API and UI remain at `127.0.0.1:8000` and `127.0.0.1:8501`. `OPENAI_API_KEY` remains API-only; the worker never calls an LLM.

### Exercise 1 — real PDF end-to-end

Open http://127.0.0.1:8501. Upload a **new, text-based PDF**, press **Add PDF to search**, then **Refresh ingestion status**. The UI should show queued/running, then succeeded, and the document should appear in Sources. Search for a distinctive phrase from it: it should be found without restarting FastAPI.

Or run:

```powershell
python scripts/smoke_ingestion_jobs.py "C:\path\to\my-paper.pdf"
```

This script uses the existing Python `requests` dependency, uploads the selected PDF, polls the job and checks that it appears in `/documents`. It will also work for a *duplicate* document, returning a succeeded job with `duplicate=true`.

To look directly at the job API from PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready
Invoke-RestMethod http://127.0.0.1:8000/ingestion-jobs/<the-job-id>
```

For problems inspect:

```powershell
docker compose @cfg logs --tail 100 api worker redis db
```

## Safety and current limitations — *intentional Sprint 1 scope*

1. **This is not crash-safe yet.** If FastAPI crashes after committing `queued` but before Redis enqueue, a job can be stranded. If a worker is forcibly killed while `running`, PostgreSQL may retain that state indefinitely. We deliberately implement reconciliation, retries and backoff in Sprint 2–3.
2. **Only one worker** should run. Jobs are handled serially; existing direct `POST /documents` is still supported for compatibility. Do not use multiple workers or multiple API replicas with this in-memory index design.
3. `GET /health/ready` now checks PostgreSQL and Redis when async mode is enabled. `GET /health/live` doesn't query dependencies.
4. **API read overhead:** `GET /documents`, `/search`, `/ask`, PDF reads, and `/health` compare metadata to detect worker updates. This costs a PostgreSQL query per read; appropriate for our tiny corpus only.
5. All services use the same `data/app` bind mount. The PDF staging copy lives under `data/app/staging`. The worker cleans it on normal success or committed failure; a hard crash can leave an orphan.
6. Job failure messages shown via API are intentionally generic for server errors; inspect worker logs for detailed stack traces.
7. This is a **localhost-only teaching prototype** with no authentication. Do not expose it to the public internet.

## Checkpoint for Sprint 1

Successful result means: `POST /ingestion-jobs` returns 202 fast, `GET /ingestion-jobs/{id}` reaches `succeeded`, a new PDF is searchable without API restart, the old 109 local tests pass and the existing 7 live PostgreSQL tests pass **after** Alembic upgrade to 0002.

**Next, NOT now:** Retry/backoff/timeout handling, stale-running reconciliation, failure injection (kill worker, restart Redis), measured recovery behavior.
