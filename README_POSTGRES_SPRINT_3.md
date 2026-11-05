# Mini-Hackathon #2 — Sprint 3.1: PostgreSQL foundation

## Boundaries / safety

This patch is **additive only**: no existing files are replaced. It adds PostgreSQL,
SQLAlchemy metadata models, an Alembic migration, and contract tests. **FastAPI
still reads `data/app/registry.json`**, and PDFs / chunks / BM25 stay where they
are. PostgreSQL does **not** yet own document metadata: migration/backfill and
atomic file-DB workflows are deliberately a later substep.

Your prior archive contained the *pre-Docker* version of the app. Merge this patch
into your **actual current working directory**, which already contains
`compose.yaml`, `Dockerfile`, and the previous overlay changes.

## Installation (PowerShell, project root)

1. Check `git status --short`. Commit your current Docker changes on your feature branch before overlaying this patch; review staged files and never stage `.env` or secrets.
2. Extract the overlay to your current project root.
3. Add to your existing **local** `.env` (do not commit it):

   `MARINE_DB_PASSWORD=<a-long-random-password>`

4. Inspect configuration, start only the new database, then apply migrations:

```powershell
docker compose -f compose.yaml -f compose.postgres.yaml config --quiet
docker compose -f compose.yaml -f compose.postgres.yaml up -d db
docker compose -f compose.yaml -f compose.postgres.yaml ps db
docker compose -f compose.yaml -f compose.postgres.yaml build db-migrate
docker compose -f compose.yaml -f compose.postgres.yaml --profile tools run --rm db-migrate
```

5. Check migration state using the same migration image:

```powershell
docker compose -f compose.yaml -f compose.postgres.yaml --profile tools run --rm db-migrate alembic -c alembic.ini current
```

   The final `alembic -c alembic.ini current` overrides the service default
   command, which runs `alembic ... upgrade head`.

6. Test the Python DB contracts (needs `requirements-db.txt` locally):

```powershell
python -m pip install -r requirements-db.txt
python -m pytest -q
```

Expected new tests: +5 (relative to the app version you have installed). Total
counts depend on which earlier sprint patches are present.

## What we will do next

- Backfill existing upload records from `registry.json` using idempotent inserts.
- Replace JSON-registry metadata access with a repository abstraction, **after**
  verifying that all records are migrated.
- Keep PDF and extracted chunk storage on persistent disk; DB transactions alone
  cannot roll back filesystem writes. Plan compensation / outbox if needed.
- Design search-index synchronization before running multiple API workers.

**Caution:** Do not delete `data/app/registry.json`, original PDF files, or
`marine_pgdata`; do not run `alembic downgrade base` on real document data.
Do not publish the PostgreSQL port to your host/network unless needed.
