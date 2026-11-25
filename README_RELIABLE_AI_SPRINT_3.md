# Reliable AI Systems — Sprint 3: Observability

**Overlay onto the user's Marine Evidence Finder AFTER Sprint 2 and its automatic
StartedJobRegistry cleanup hotfix.** The overlay changes only the files named in
its ZIP. It does not migrate/reset PostgreSQL, delete Redis, change retrieval,
change PDF storage, or change the retry state machine.

## 0. What we learned in Sprint 2

The SIGKILL experiment completed `queued → running → [worker killed] →
queued → running → succeeded` with the second delivery `<job_id>-a2`.
The initially stuck `started` RQ record was automatically cleaned and marked
`AbandonedJobError` after the Sprint 2 hotfix. In Sprint 3 we are making the
state of that distributed process **visible without opening 5 terminals**.

### Scope and guarantees

1. Structured application JSON log events with UTC timestamp, service, level,
   request_id (for HTTP), and job_id/rq_job_id (for durable processing events).
   We do **not** emit PDFs, document names, research questions, raw request
   paths, API keys or arbitrary HTTP bodies in our own structured fields.
   Third-party RQ/Uvicorn output and exception messages may still be plain
   text or include information: this is not an end-to-end redaction system.
2. HTTP Prometheus metrics: request counts by **route template** (not raw IDs),
   status, method; duration histogram; in-flight gauge. `/metrics` and health
   probes are intentionally omitted from HTTP traffic metrics.
3. Durable ingestion metrics: counts by PostgreSQL status (queued, running,
   succeeded, failed), oldest running attempt age; Redis RQ queue depth;
   last healthy Reconciler pass from a Redis key with 120-second TTL.
4. `/ops/status` JSON for a quick glance; `/metrics` for Prometheus scraping.
5. Additive `compose.observability.yaml` running Prometheus (localhost:9090)
   and Grafana (localhost:3000), with 10 provisioned panels, sample alerts.
6. New tests and a read-only `scripts/smoke_observability.py`.

**Limitations:** metrics are from one API process (our existing Compose starts
`--workers 1`); no Prometheus multiprocess registry. The worker and reconciler
are NOT independently scraped: their durable outcomes are represented via
PostgreSQL and Redis. Grafana/Prometheus are *local teaching services*, not a
secured Internet-facing observability stack. Prometheus alert rules alone do
not send notifications; that would require Alertmanager and notification setup.

## 1. Install (PowerShell, repo root)

Back up local changes before overlaying: it overwrites existing source files.

```powershell
$cfg = @(
  '-f', 'compose.yaml',
  '-f', 'compose.postgres.yaml',
  '-f', 'compose.metadata.yaml',
  '-f', 'compose.jobs.yaml'
)

# Inspect changes first, and save or commit personal modifications.
git status --short

Expand-Archive `
  "$env:USERPROFILE\Downloads\marine_reliable_ai_sprint3_observability_overlay.zip" `
  -DestinationPath . -Force

# New local test dependency (also installed in Docker on build).
python -m pip install -r requirements-app.txt
python -m pytest -q

# The 5th compose file is ADDITIVE; keep the original 4 files.
$allCfg = $cfg + @('-f', 'compose.observability.yaml')

# Disable the previous chaos-test pause for routine work.
$env:MARINE_CHAOS_PAUSE_AFTER_CLAIM_SECONDS = '0'

docker compose @allCfg config --services
docker compose @allCfg up -d --build api worker reconciler prometheus grafana
docker compose @allCfg ps

python scripts/smoke_observability.py
```

No Alembic migration: the latest revision remains `0003_ingestion_reliability`.
Never use `docker compose down -v` here, as it destroys persisted volumes.

### URLs

- JSON status: http://127.0.0.1:8000/ops/status
- Plaintext Prometheus metrics: http://127.0.0.1:8000/metrics
- Prometheus targets: http://127.0.0.1:9090/targets
- Prometheus alert status: http://127.0.0.1:9090/alerts
- Grafana: http://127.0.0.1:3000/d/marine-reliable-ai-s3

Grafana has **anonymous Viewer access only**; no login form is provided. Ports
are bound to `127.0.0.1` to avoid publishing this unsecured local setup.

## 2. What each file does

- `requirements-app.txt`: installs `prometheus-client` for API and job Docker images.
- `src/marine_evidence/observability.py`: JSONLogFormatter, metrics registry,
  read-only state snapshot, Redis heartbeat with TTL, UUID request IDs.
- `src/marine_evidence/api.py`: HTTP middleware; `X-Request-ID`; `/metrics`;
  `/ops/status`; `ingestion_job_accepted` log.
- `src/marine_evidence/ingestion_jobs.py`: JSON worker application events
  `ingestion_attempt_started`, `ingestion_attempt_error`,
  `ingestion_attempt_succeeded`, with job and delivery IDs and duration.
- `src/marine_evidence/ingestion_job_repository.py`: SQL `GROUP BY status` and
  `MIN(started_at)` instead of loading every job into Python.
- `src/marine_evidence/job_reconciler.py`: heartbeat recorded after successful
  reconciliation pass; structured retry and enqueue events; KEEP Sprint 2 RQ
  started-registry cleanup in this file.
- `compose.jobs.yaml`: `MARINE_LOG_FORMAT=json` for API, worker, reconciler.
- `compose.observability.yaml`: localhost Prometheus + Grafana sidecars.
- `observability/prometheus.yml`: scrape `api:8000/metrics` every 5 seconds.
- `observability/alerts.yml`: API down, reconciler heartbeat stale, very old running job.
- `observability/grafana/`: provisioned Prometheus datasource and dashboard.
- `scripts/smoke_observability.py`: read-only acceptance checks.
- `tests/test_observability.py`: cardinality/privacy, request IDs, log format,
  SQL aggregates, Redis heartbeat, metrics and dashboard tests.

## 3. Why this architecture?

**Durable truth vs execution transport:** PostgreSQL is the source of truth for
job states; Redis/RQ is the transport. After an abrupt worker crash, its
in-memory counters vanish. Reporting job status by scanning the DB avoids
this misleading reset. RQ `.count` reports waiting deliveries only; running
jobs are counted by PostgreSQL, so the two gauges are not interchangeable.

**Gauge vs counter:** HTTP requests are a counter (monotonic process-local),
so a query can use `rate()`. Number of running jobs is a gauge (may increase
or decrease); do not apply `rate()` to the number of running jobs to infer
throughput. Overall successes in the DB are a gauge of current accumulated
rows, not a Prometheus counter.

**Histogram:** the per-route request duration is a histogram with predefined
buckets. Grafana computes 95th percentile from bucket **rates** using
`histogram_quantile()`. A single request does not yield a robust latency
estimate, and with no traffic the plot may be blank.

**Cardinality:** never label a Prometheus metric with an unbounded value like
job_id, source_id, question, filename or raw URL. There may be millions of
such values. We label by `GET /ingestion-jobs/{job_id}` instead.

**Correlation IDs:** HTTP requests are assigned new `X-Request-ID`; event
`ingestion_job_accepted` logs both the request ID and the durable job ID.
Worker and Reconciler events log the same durable job ID, plus per-attempt
RQ delivery ID. You can follow one operation across processes by `job_id`
without adding a per-job metric label.

**Heartbeat:** Reconciler sets `marine:observability:reconciler_last_success`
in Redis after a reconciliation pass with zero reported errors. The key
expires after 120 seconds, so an old heartbeat cannot appear healthy forever.
Our API exports the stored UTC Unix timestamp, or zero to Prometheus when
missing. Prometheus alert `MarineReconcilerHeartbeatMissing` detects zero or
age >120 seconds, for 1 minute. It does *not* prove RQ job processing is
working, just that reconcile passes finished without reported errors.

**Safe failure behavior:** if snapshot collection throws (PostgreSQL or Redis
unavailable), `/metrics` replies HTTP 503. The Prometheus target becomes
`DOWN` rather than reporting a fake zero count. The standard liveness probe
is intentionally independent of observability dependencies.

## 4. Read metrics by hand

From PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/ops/status
(Invoke-WebRequest http://127.0.0.1:8000/metrics).Content -split "`n" |
  Select-String 'marine_ingestion_jobs|marine_rq_queue_depth|marine_reconciler_last_success'
```

Some useful PromQL expressions:

```promql
sum(rate(marine_http_requests_total[5m]))
```

```promql
histogram_quantile(
  0.95,
  sum by (le, route) (rate(marine_http_request_duration_seconds_bucket[5m]))
)
```

```promql
marine_ingestion_jobs{status="running"}
```

```promql
time() - marine_reconciler_last_success_timestamp_seconds
```

Look for JSON lines in:

```powershell
docker compose @allCfg logs --tail 40 api worker reconciler
```

Example application event (illustrative, not an actual observed log):

```json
{"timestamp":"2026-11-19T12:43:37.324+00:00","level":"WARNING","service":"reconciler","logger":"marine_evidence.job_reconciler","message":"Recovering abandoned attempt job=... old=... new=...","event":"ingestion_attempt_recovered","job_id":"<job_id>","rq_job_id":"<job_id>-a2"}
```

Worker/RQ/Uvicorn third-party logs may remain plain text; `MARINE_LOG_FORMAT=json`
controls logs emitted via our Python logging configuration, not every
underlying library or Docker startup message.

## 5. Hands-on acceptance exercises

**A. Normal ingestion.** Upload a NEW PDF (not a byte-for-byte duplicate).
Compare `/ops/status` with Grafana `Queued`, `Running`, `Succeeded` and `RQ queue
depth` panels. Sampled gauges may miss a fast `running` state; that is normal.

**B. API traffic.** Repeat requests to `/health` or `/search`; look at
`Requests/sec by route` and `HTTP latency p95`. Wait several scrapes. The
HTTP middleware excludes `/metrics`, `/health/live`, and `/health/ready` to
avoid health-check noise and self-scrape feedback.

**C. Reconciler died.** Stop only `reconciler`:

```powershell
docker compose @allCfg stop reconciler
```

After about two minutes, `marine_reconciler_last_success_timestamp_seconds`
will become zero (TTL expired). The Prometheus stale-heartbeat alert is then
eligible after its `for: 1m` delay. Restore immediately after the test:

```powershell
docker compose @allCfg up -d reconciler
```

**D. SIGKILL worker, again.** Reuse the prior procedure with
`MARINE_CHAOS_PAUSE_AFTER_CLAIM_SECONDS=90`, kill only the worker after
`CHAOS pause after claim`, restart with `0`. Watch queued/running/oldest age;
watch structured `ingestion_attempt_recovered` then `succeeded`. Avoid
manually cleaning StartedJobRegistry.

## 6. What's NOT included

- Distributed tracing (OpenTelemetry/Jaeger); request ID + job ID are basic
  correlation, not a cross-service trace/span graph.
- Metrics-exporting HTTP servers inside worker and reconciler; no Pushgateway.
- Durable/event counters for each worker process; use DB gauges and JSON
  logs rather than inventing crash-persistent in-memory counters.
- Automatic notifications (Alertmanager) or production access control.
- Retention/cleanup policy for old `ingestion_jobs` rows; values such as
  `succeeded` and `failed` represent all retained jobs.
- Multiple API worker processes and Prometheus multiprocess mode.

## 7. Interview checkpoints

1. Why are request durations histograms, but running jobs gauges?
2. Why is a Prometheus `job_id` label dangerous? How do we correlate one job?
3. What happens to process-local counters after SIGKILL and why do we query DB?
4. Why does a missing reconciler heartbeat not prove a specific worker died?
5. Why do we use `X-Request-ID` without trusting a client-provided ID?
6. What information does RQ queue depth miss?
7. Why can't `rate(marine_ingestion_jobs{status="succeeded"}[5m])` reliably
   measure throughput?
8. How do alerts differ from notifications?
9. Which logs are still unstructured and what would you change in production?
10. What would need changing for multiple Uvicorn worker processes?
