# Marine Evidence Finder — Sprint 2 hotfix: automatic RQ abandoned-job detection

## What happened during the real chaos test

- The first worker was killed by `SIGKILL` after claiming a PDF ingestion job.
- PostgreSQL correctly retained `status=running`, `attempts=1`.
- Redis Queue (RQ 2.12.0) still returned `started` for that abandoned delivery.
- `reconcile_once()` only checked `job.get_status(refresh=True)`. It refused to schedule a retry while RQ said `started`.
- An **interactive diagnostic call** to `queue.started_job_registry.get_job_ids()` triggered RQ's registry cleanup. RQ then moved the expired job to `FailedJobRegistry` with `AbandonedJobError`. The existing reconciler recovered it; attempt `-a2` succeeded.

## The fix

File: `src/marine_evidence/job_reconciler.py`.

Each reconciliation pass first reads unfinished rows from PostgreSQL. **If any row is `running`**, it calls:

```python
queue.started_job_registry.get_job_ids()
```

On the RQ 2.12.0 version used in the user's Docker logs, `get_job_ids()` performs native registry cleanup by default. It detects expired started entries, updates their RQ state, and permits the same reconciliation pass to observe `failed`. The **existing** `plan_retry`, attempt-ownership, backoff and enqueue logic then takes over. Importantly, the reconciler does not make up a new heartbeat cutoff or forcibly mutate Redis status.

The call is performed **before** reading the individual RQ delivery statuses; otherwise the reconciler would need to wait another polling interval. Errors in registry cleanup are logged and retried on the next pass; they do not silently stop the reconciler process.

New regression tests model `started` becoming `failed` during the registry scan and verify that genuinely active `started` jobs are left alone.

### Scope and limits

- **No** new SQL schema, Alembic migration, Redis key manipulation, or changes to API/worker/RAG.
- This fix makes detection **automatic after RQ's own expiry rules deem an attempt abandoned**. It does **not** make recovery instantaneous. Current RQ delivery `job_timeout=300` seconds; actual cleanup/retry timing depends on RQ registry expiry, so allow several minutes.
- If a worker is *hung but RQ still considers its delivery alive*, this particular change will not force it to fail. Heartbeat/lease-based detection is a separate design choice requiring careful double-execution protection.
- One reconciler and one worker remain the supported teaching configuration.
- The patch was exercised with FakeRQ and existing local tests, **not** with live Redis/PostgreSQL/Docker in this environment. The following experiment is required to validate the real deployment.

## Install over your **existing Sprint 2** project (Windows PowerShell)

Your repository must already have `migrations/versions/0003_ingestion_reliability.py` and `src/marine_evidence/job_reconciler.py` from Sprint 2. Save uncommitted edits first; the overlay replaces only the reconciler and its recovery tests (plus this README).

```powershell
# In marine-evidence-finder root
$cfg = @(
  '-f', 'compose.yaml',
  '-f', 'compose.postgres.yaml',
  '-f', 'compose.metadata.yaml',
  '-f', 'compose.jobs.yaml'
)

git status --short
Expand-Archive "$env:USERPROFILE\Downloads\marine_reliable_sprint2_auto_recovery_fix.zip" -DestinationPath . -Force
python -m pytest -q

docker compose @cfg up -d --build --no-deps reconciler
docker compose @cfg ps
docker compose @cfg logs --tail 40 reconciler
```

Expected on the reconstructed project: `119 passed, 5 skipped`. The five skipped tests require the dedicated PostgreSQL test database. There is **no** database migration for this hotfix. Do **not** use `docker compose down -v`.

## Retest SIGKILL **without** touching RQ registry by hand

1. From a PowerShell session with `$cfg` set, start the worker with a long pause after claim:

```powershell
$env:MARINE_CHAOS_PAUSE_AFTER_CLAIM_SECONDS = '90'
docker compose @cfg up -d --force-recreate --no-deps worker
docker compose @cfg exec worker printenv MARINE_CHAOS_PAUSE_AFTER_CLAIM_SECONDS
```

It should print `90`.

2. Create a **new** text PDF for this experiment (to avoid an existing duplicate):

```powershell
@'
import fitz
from uuid import uuid4
from pathlib import Path
p = Path('reliable_chaos_autorecovery.pdf')
doc = fitz.open()
page = doc.new_page()
text = ('This unique PDF tests automatic Redis Queue abandoned job recovery. '
        'It describes whale vocal communication and underwater acoustic propagation. '
        'Chaos test identifier ' + uuid4().hex + '. ')
page.insert_text((72, 72), text, fontsize=10)
doc.save(p)
doc.close()
print(p.resolve())
'@ | python
```

3. Upload the PDF through Streamlit. Monitor worker logs in a separate terminal:

```powershell
docker compose @cfg logs -f worker
```

As soon as you see `CHAOS pause after claim`, run:

```powershell
docker compose @cfg kill -s SIGKILL worker
$env:MARINE_CHAOS_PAUSE_AFTER_CLAIM_SECONDS = '0'
docker compose @cfg up -d --force-recreate --no-deps worker
```

4. Observe **only** the public job API and container logs; **do not invoke** `StartedJobRegistry.get_job_ids()` by hand during the experiment. Substitute the real job ID:

```powershell
$jobId = 'PASTE_JOB_ID_HERE'
for ($i = 0; $i -lt 90; $i++) {
  $j = Invoke-RestMethod "http://127.0.0.1:8000/ingestion-jobs/$jobId"
  Write-Host "$(Get-Date -Format HH:mm:ss)  $($j.status)  attempts=$($j.attempts)  delivery=$($j.rq_job_id)"
  if ($j.status -in @('succeeded','failed')) { break }
  Start-Sleep -Seconds 10
}

docker compose @cfg logs --since 20m reconciler worker
```

The polling code waits up to 15 minutes only to observe; it does **not** alter registry state. Expected positive evidence: the **reconciler container** logs RQ's `AbandonedJobError` cleanup and then `Recovering abandoned attempt ... new=...-a2`, followed by `Enqueued persisted job ...-a2`; PostgreSQL reports `status=succeeded`, `attempts=2`. If it stays `running`, share the current job state plus both containers' logs: do not restart Redis, clear registries, or wipe PostgreSQL.

**After the test**, keep `MARINE_CHAOS_PAUSE_AFTER_CLAIM_SECONDS=0` and recreate the worker if it is still paused.
