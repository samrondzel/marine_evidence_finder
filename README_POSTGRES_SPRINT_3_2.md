# Marine Evidence Finder — Sprint 3.2: PostgreSQL metadata cutover

This is an **additive metadata cutover** to the existing Docker + PostgreSQL foundation, not a new RAG or retriever implementation. The `bm25` chunk text and PDF bytes remain on persistent disk. Uploaded-document **metadata** (`source_id`, SHA256, filename, title, pages, chunk count, timestamp) lives in PostgreSQL after cutover.

## Safety notes before touching data

- Start from the **working project containing `compose.yaml`, `compose.postgres.yaml`, and Alembic migration `0001_uploaded_documents`**. Your user-provided ZIP was older; do **not** unpack this into a clean checkout that lacks the previous sprints.
- Do not delete `data/app/registry.json`, `data/app/pdfs`, `data/app/chunks`, or the named Docker volume `marine_pgdata`. Make a backup of `data/app` before migrating.
- The `.env` file with `MARINE_DB_PASSWORD` stays local; do not commit it. `PGPASSWORD` is supplied to the API as a runtime environment variable (not baked into an image).
- We still run **one Uvicorn worker**. PostgreSQL handles metadata transactions, but multiple workers would each maintain an unsynchronized **in-memory BM25 index**; concurrent upload support across workers is **not** implemented.
- The old `registry.json` becomes a **backup only**. The API does not continue editing it in PostgreSQL mode. **Never rerun the one-time legacy backfill after deleting documents in PostgreSQL mode**: old JSON rows could be reintroduced.
- If DB is unavailable at startup, the API refuses to start. `/health/ready` checks DB connectivity and can return HTTP 503.

## Included files

| File | Function |
| --- | --- |
| `src/marine_evidence/metadata_repository.py` | SQLAlchemy repository: SELECT / INSERT / DELETE / transactional backfill |
| `src/marine_evidence/backfill_metadata.py` | Validated, idempotent import of existing upload metadata from JSON to PostgreSQL |
| `src/marine_evidence/corpus_store.py` | Optional repository integration while preserving legacy JSON mode |
| `src/marine_evidence/api.py` | Opt-in PostgreSQL mode and readiness checking |
| `Dockerfile.metadata` | Same runtime image, with additional PostgreSQL libraries |
| `compose.metadata.yaml` | Docker Compose override that activates DB metadata mode for API |
| `tests/test_metadata_integration.py` | SQLite-backed integration tests and failure injection |
| `ADR_METADATA_POSTGRES.md` | Architectural trade-offs and remaining limitations |

## Step 1 — Install and validate (Windows PowerShell)

From the project root with `.venv` active, after backing up `data/app` and committing existing changes:

```powershell
Expand-Archive `
  "$env:USERPROFILE\Downloads\marine_postgres_sprint3_2_integration_overlay.zip" `
  -DestinationPath . -Force
python -m pip install -r requirements-db.txt
python -m pytest -q
```

Expected on the exact accumulated sprint version: **100 passed** (92 existing + 8 new). The test suite uses SQLite for database operations, so you still need the real PostgreSQL smoke test below.

## Step 2 — Confirm the *previous* Alembic revision was applied

The pasted log ended when the migration container was **created**, not at the successful Alembic upgrade. Check the actual state:

```powershell
docker compose -f compose.yaml -f compose.postgres.yaml --profile tools run --rm db-migrate alembic -c alembic.ini current
```

Expected: `0001_uploaded_documents (head)` (or a current revision string containing `0001_uploaded_documents`). If no revision is listed, run the upgrade now:

```powershell
docker compose -f compose.yaml -f compose.postgres.yaml --profile tools run --rm db-migrate
```

**Do not continue to cutover until the expected revision is confirmed.** No new DDL migration is needed in Sprint 3.2; the existing table schema is reused.

## Step 3 — Build the DB-capable API and do a read-only dry-run

These commands include three Compose files. The third file **overrides** the API to use PostgreSQL as metadata backend. It does **not** expose the DB port to the host.

```powershell
docker compose -f compose.yaml -f compose.postgres.yaml -f compose.metadata.yaml config --quiet
docker compose -f compose.yaml -f compose.postgres.yaml -f compose.metadata.yaml build api

docker compose -f compose.yaml -f compose.postgres.yaml -f compose.metadata.yaml run --rm api python -m marine_evidence.backfill_metadata --dry-run
```

The validator checks each legacy PDF's SHA-256, the presence of its chunk JSONL file, chunk count and provenance. Expect something like `Legacy uploads verified: 1; to insert: 1; already in DB: 0` for your previously uploaded robotics paper.

The dry-run queries the DB but does **not** write data. Fix any errors (missing artifact, wrong checksum, missing migration) before proceeding.

## Step 4 — One-time data backfill

```powershell
docker compose -f compose.yaml -f compose.postgres.yaml -f compose.metadata.yaml run --rm api python -m marine_evidence.backfill_metadata --apply
```

Expected: `Backfill committed: inserted=1; existing=0`, if one legacy upload exists. Another run *before switching the API* should be idempotent, but **do not make re-running it a routine**.

This is a **data migration** (existing rows moved to a different source of truth), not an Alembic **schema migration** (DDL table creation). They are separate operations.

## Step 5 — Switch the running API to PostgreSQL metadata

```powershell
docker compose -f compose.yaml -f compose.postgres.yaml -f compose.metadata.yaml up -d --build api ui
docker compose -f compose.yaml -f compose.postgres.yaml -f compose.metadata.yaml ps
```

Check from PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready
(Invoke-RestMethod http://127.0.0.1:8000/documents).documents | Select-Object source_id, filename, uploaded
```

You should still see the original eight benchmark PDFs and the robotics upload: **9 documents, 286 chunks** on the corpus we inspected. Make a search request and open the uploaded PDF from the UI.

### Test persistence and actual DB ownership

1. Upload a **new, different** PDF via Streamlit.
2. Confirm it shows up under `/documents`.
3. Restart only the API: `docker compose -f compose.yaml -f compose.postgres.yaml -f compose.metadata.yaml restart api`.
4. Check that the upload is still searchable and its PDF opens. The old `registry.json` should remain unchanged.
5. Delete the new test upload in Streamlit, restart the API, and verify it **stays deleted**. This demonstrates that the PostgreSQL row (not stale JSON) controls visibility.

## Important limitations / recovery

- A PostgreSQL transaction **cannot atomically commit a file on disk**. For normal errors, the service compensates when possible. If the outcome of a DB commit is unknown (e.g. lost connection), the code **preserves the uploaded files** for manual recovery rather than risk deleting a PDF referenced by a committed row. The API returns HTTP 503. Unexpected orphan files should be diagnosed, not blindly deleted.
- On deletion, PostgreSQL metadata is removed first, followed by best-effort file cleanup. A crash can leave an **orphan file**, which the index ignores after restart.
- This is still a **local development deployment**, not publicly safe: no authentication, quota enforcement or distributed locking. Use a single API worker.
- If your API is accidentally started without the **third Compose file**, it falls back to legacy JSON mode, and the document listing may be stale. Keep using all three Compose files from cutover onward.
- Do not run `docker compose down -v` or Alembic downgrades on real data. Don't delete named volumes to troubleshoot an error.
- Do not switch to DB mode until the backfill succeeded. If API startup then fails, check logs with `docker compose -f compose.yaml -f compose.postgres.yaml -f compose.metadata.yaml logs api` and compare `uploaded_documents` with the backed-up registry before any rollback.

## Interview preparation

1. What's the difference between **schema migration** (Alembic) and **data backfill** (this CLI)?
2. Why does a **PostgreSQL COMMIT** not guarantee an atomic PDF+row operation?
3. After this sprint, why are we **still using one Uvicorn worker**?
