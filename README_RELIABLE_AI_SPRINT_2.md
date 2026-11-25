# Marine Evidence Finder — Reliable AI Systems, Sprint 2: Failure Handling

This ZIP is an **overlay** for your existing Marine Evidence Finder with Sprint 1 already installed. Do **not** delete `data/app/`, your PostgreSQL data volume, or the original corpus. The overlay replaces worker code, including any manually inserted `time.sleep(60)` fault injection from the previous exercise. A controlled pause is now available via an environment variable (off by default).

## What changed

- **PostgreSQL is durable job intent:** migration `0003_ingestion_reliability` adds `attempts`, `rq_job_id`, `retry_at` and an index on job status. Existing `ingestion_jobs` rows are retained; old running rows are backfilled as attempt 1.
- **Attempt ownership:** each RQ retry has its own delivery ID. PostgreSQL conditional updates reject stale workers, and only the current delivery may mark a job successful.
- **Recovery daemon:** a new `reconciler` service polls unfinished PostgreSQL jobs and RQ state. If RQ says an executing attempt failed (including `AbandonedJobError`), the daemon schedules another attempt with exponential backoff. After the configured budget it records `failed`. It also repairs the narrow crash window when SQL committed a `queued` job but Redis enqueue never happened.
- **Ordinary processing failures:** a worker can schedule a retry for transient errors; invalid PDFs and missing staging files fail terminally.
- **Retry-safe artifacts:** for the PostgreSQL ingestion path, a repeated processing attempt can adopt PDF/chunk files left behind by a crash **only if their bytes exactly match** the intended document. Conflicting orphaned artifacts are rejected rather than overwritten.
- **Controlled fault injection:** optional `MARINE_CHAOS_PAUSE_AFTER_CLAIM_SECONDS` on `worker`. Defaults to `0`; do not hard-code sleep in the worker again.
- **Tests:** `tests/test_reliable_recovery.py` exercises RQ failure → Postgres retry, stale ownership, attempt limits, missing Redis enqueue, exponential backoff, and migration. `tests/test_ingestion_jobs.py` includes one additional orphan-artifact test and updated migration-head assertion.

## Installation (Windows PowerShell, project root)

**Back up first:** commit/backup your modified source; back up `data/app/` and your PostgreSQL named volume. Avoid `docker compose down -v`.

```powershell
$cfg = @('-f','compose.yaml','-f','compose.postgres.yaml','-f','compose.metadata.yaml','-f','compose.jobs.yaml')
git status --short
docker compose @cfg stop worker
Expand-Archive "$env:USERPROFILE\Downloads\marine_reliable_ai_sprint2_overlay.zip" -DestinationPath . -Force
python -m pytest -q

docker compose @cfg build db-migrate
docker compose @cfg --profile tools run --rm db-migrate
docker compose @cfg --profile tools run --rm db-migrate alembic -c alembic.ini current
# Expected: 0003_ingestion_reliability (head)

docker compose @cfg up -d --build api worker reconciler ui redis
docker compose @cfg ps
docker compose @cfg logs --tail 80 reconciler worker
```

### Check recovery of a stuck task (if you have one)

If you previously killed the worker while it was processing, find the actual `job_id` for that task and query it:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/ingestion-jobs/YOUR_JOB_ID
docker compose @cfg logs --tail 100 reconciler worker
```

The original staged file must still exist for a retry to succeed. If it is missing, the task must eventually fail rather than silently succeed. RQ must first classify an abandoned execution as failed; a still-`started` RQ job is not immediately retried. If you have no stuck task, skip this step.

### Repeat a controlled crash (optional)

Set `MARINE_CHAOS_PAUSE_AFTER_CLAIM_SECONDS=60` in your project's `.env`, then recreate the worker:

```powershell
docker compose @cfg up -d --force-recreate worker
docker compose @cfg logs -f worker
```

Upload a **new** text PDF. When logs show `CHAOS pause after claim`, kill it from another terminal:

```powershell
docker compose @cfg kill -s SIGKILL worker
docker compose @cfg up -d worker
docker compose @cfg logs -f worker reconciler
```

Once RQ marks the old execution failed, reconciler should reschedule it; the API should change from `running` to `queued`, then `running`, then `succeeded` (or terminal `failed` if all attempts fail). Restore `MARINE_CHAOS_PAUSE_AFTER_CLAIM_SECONDS=0` and recreate worker after the test; otherwise every retry pauses too.

## Configuration and limits

| Variable | Default | Meaning |
|---|---:|---|
| `MARINE_JOB_MAX_ATTEMPTS` | `3` | Maximum processing attempts |
| `MARINE_JOB_BACKOFF_BASE` | `2` | Base seconds; backoff grows with attempt number |
| `MARINE_RECONCILE_INTERVAL_SECONDS` | `5` | Poll interval in seconds |
| `MARINE_CHAOS_PAUSE_AFTER_CLAIM_SECONDS` | `0` | Test pause only; production value 0 |

### What is and is not verified

The Sprint 2 state-machine tests have been run locally with **SQLite and a fake RQ queue**. This package has **not** been integration-tested against your live Redis/RQ/PostgreSQL Docker stack. Do not treat it as production-grade reliability. The reconciler is intentionally **single-instance**; running two copies can race during missing-delivery enqueue. There is no distributed lease/leader election, no transactional outbox, no full concurrent-writer control over CorpusStore, and no guarantee about Redis data durability through catastrophic loss. Recovery of RQ `started` executions depends on RQ cleanup; don't assume a fixed recovery deadline.

The worker's 300s execution timeout remains an RQ timeout. A terminal `failed` job cannot be manually restarted with the same stable job ID without a separate explicit reset workflow. The current implementation classifies some parse/document errors as terminal; operators should inspect worker logs for failures before re-uploading.
