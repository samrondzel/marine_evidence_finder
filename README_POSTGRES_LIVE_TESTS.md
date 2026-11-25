# Sprint 5 — Real PostgreSQL integration tests

**Goal:** Verify the actual PostgreSQL driver, Alembic schema, metadata repository and `CorpusStore` persistence — *without modifying the running production/dev Marine Evidence database*.

This is an additive test-only sprint. It adds **no changes** to the FastAPI application, PostgreSQL schema, RAG, or actual uploads.

## Why

Existing repository tests exercise SQLAlchemy with **SQLite**. That's useful, but it doesn't prove that PostgreSQL DDL, uniqueness constraints, transactions, DB reconnection, and upload/restart behaviour work with psycopg. This sprint gives us a repeatable real-Postgres check, both locally and in GitHub Actions.

## What is included

- `tests/test_postgres_live.py`: 2 ordinary safety-unit tests and 5 live PostgreSQL tests: Alembic version, insert/read/delete, SQL constraints, transactional + idempotent backfill, PDF upload/search/restart/delete.
- `compose.pgtest.yaml`: **dedicated** test PostgreSQL container, isolated Compose project + volume, available *only* on localhost port **5433**. This is NOT the production database.
- `.github/workflows/postgres-integration.yml`: separate workflow with its own disposable PostgreSQL 16 service and explicit `alembic upgrade head` before tests. No real API keys.

## Installation and local dry-run (PowerShell)

From the same project containing `compose.yaml`, `compose.postgres.yaml`, `compose.metadata.yaml`:

```powershell
Expand-Archive "$env:USERPROFILE\Downloads\marine_postgres_live_tests_overlay.zip" -DestinationPath . -Force
python -m pip install -r requirements-db.txt
python -m pytest -q
```

Without an explicitly configured test PostgreSQL URL, the 5 live cases are **skipped**. All other tests still run. Seeing skips here is deliberate.

## Run on an isolated test PostgreSQL (PowerShell)

**Do not reuse `MARINE_DB_PASSWORD` or the main PostgreSQL database.** The test password below is intentionally non-secret and only suitable for the disposable localhost test container.

```powershell
docker compose -f compose.pgtest.yaml up -d
# Check db-test reports healthy:
docker compose -f compose.pgtest.yaml ps

$env:MARINE_TEST_DATABASE_URL = "postgresql+psycopg://marine_test:local_ci_only@127.0.0.1:5433/marine_evidence_test"
$env:DATABASE_URL = $env:MARINE_TEST_DATABASE_URL

python -m alembic -c alembic.ini upgrade head
python -m pytest -q tests/test_postgres_live.py
```

Expected: **7 passed** for this file (2 guard tests + 5 real PostgreSQL tests). Schema revision should be `0001_uploaded_documents`. If you want, run the entire suite again; it should use the disposable DB for these 5 cases.

Important: when testing is finished, remove the temporary env vars from your PowerShell session so future commands don't accidentally use the test URL:

```powershell
Remove-Item Env:MARINE_TEST_DATABASE_URL
Remove-Item Env:DATABASE_URL
```

Stopping the test instance doesn't affect the main app:

```powershell
docker compose -f compose.pgtest.yaml down
```

Do **not** add the file to the regular multi-file Compose command. The dedicated Compose project name isolates it from your application. Do not use `down -v` on the real app.

## GitHub Actions

Commit and push `tests/test_postgres_live.py`, `compose.pgtest.yaml`, `README_POSTGRES_LIVE_TESTS.md`, and `.github/workflows/postgres-integration.yml`. GitHub Actions shows **two workflows**: the existing generic CI and the new PostgreSQL integration checks.

Each job starts a fresh isolated PostgreSQL container, applies the current Alembic revision and executes real database I/O. The test suite refuses remote hosts and databases whose names do not end in `_test`.

## Interview conversation

**Q:** What is the difference between a unit test using SQLite and an integration test using PostgreSQL?

**A:** SQLite tests can validate repository behaviour and business logic quickly, but won't cover PostgreSQL-specific constraints, driver behaviour, type handling, or connection characteristics. PostgreSQL integration tests exercise the actual deployed database engine and schema migrations, trading execution speed for higher fidelity.

**Known limitations:** These tests do not prove atomicity between filesystem and SQL transactions, multi-worker BM25 synchronization, or cloud scalability. Those require separate architecture work and load/fault-injection tests.
