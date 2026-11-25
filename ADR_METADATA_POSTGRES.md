# ADR 0003 — PostgreSQL owns uploaded-document metadata

**Status:** Accepted for single-worker local MVP, 2026-11-05.

## Context

`CorpusStore` formerly saved `data/app/registry.json` and per-upload PDF/chunk files. This JSON registry works on a single local process but is not a robust multi-process metadata database. Sprint 3.1 introduced PostgreSQL `uploaded_documents` via Alembic `0001_uploaded_documents` but had not yet connected the API.

## Decision

1. Use `UploadedDocumentRepository` (SQLAlchemy, short transactions) for metadata and keep PDF/chunks on the persistent filesystem. PostgreSQL is authoritative **only when `MARINE_METADATA_BACKEND=postgres`**.
2. Keep JSON fallback for existing tests and local scripts. In PG mode, JSON is a **read-only migration backup**; do not dual-write it.
3. Verify legacy artifacts (file SHA-256, chunk files, provenance) and import rows via an **explicit one-time dry-run/apply command**, before activating the API in PG mode.
4. Do **not** run `Base.metadata.create_all` at application startup. Alembic handles all DDL changes; the app expects the schema to exist.
5. `/health/ready` checks PostgreSQL availability. If DB is down on startup, fail fast rather than silently switch to JSON.
6. Stay at **one API worker**, because BM25 remains a process-local rebuilt index even though metadata insert/delete uses database transactions.

## Failure behavior

- **Upload:** extract and build new index, write PDF/chunks to stable paths, then insert metadata in one DB transaction, then publish the new in-memory BM25 index. On a DB insert error, check DB state; delete files only when the row is definitely absent. If commit outcome is ambiguous, leave the files for inspection, report an error and reconcile before retrying.
- **Delete:** commit removal of metadata first, update in-memory index, then attempt file cleanup. If interrupted before cleanup, orphan files are not referenced by DB and will not be indexed after restart.
- **Backfill:** SQLAlchemy transaction inserts missing legacy records. Conflicts abort the transaction. Source artifacts are never deleted or overwritten by the importer.

## Alternatives considered

- **Continue writing JSON:** simple and fast but poor concurrent-writer behavior, no SQL transactions, awkward query support.
- **Write to both JSON and PostgreSQL:** tempting migration convenience, but creates two sources of truth and ambiguous recovery. Rejected.
- **Store PDF BLOBs in PostgreSQL:** would provide stronger atomicity but increases DB/storage load and changes document serving; deferred while we learn storage trade-offs.
- **Use object storage and transactional outbox:** more scalable long-term, but out of scope for the 20-hour mini-hackathon.

## Known limitations and next iterations

- No cross-process locking or distributed index refresh. **Multi-worker FastAPI is unsupported**.
- Database and filesystem cannot participate in the same ACID transaction. Add a reconciliation job / durable task queue before deploying to multiple machines.
- Backup both the PostgreSQL volume and the upload filesystem together; only backing up the DB does not preserve the actual PDF text.
- Add integration tests against a real disposable PostgreSQL service in CI; current tests exercise the repository on SQLite and a local corpus in an isolated environment, not Docker Engine.
- Authentication, upload authorization and malicious-file scanning are not implemented. Do not publish this service to the Internet.
