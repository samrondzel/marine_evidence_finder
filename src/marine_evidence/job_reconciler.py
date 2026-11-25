"""A single, polling recovery daemon for abandoned RQ ingestion attempts.

Uses the PostgreSQL job row as durable intent; Redis/RQ as execution transport.
It first asks RQ to clean expired StartedJobRegistry entries, then checks states.
It never requeues an attempt RQ *still* reports as queued/started.
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timezone

from .db_connection import make_engine
from .ingestion_job_repository import IngestionJobRepository
from .job_delivery import enqueue_delivery
from .config import AppPaths
from .observability import configure_logging, publish_reconciler_heartbeat

logger = logging.getLogger(__name__)
ACTIVE_RQ = frozenset(('queued', 'started', 'deferred', 'scheduled'))
FAILED_RQ = frozenset(('failed', 'stopped', 'canceled', 'finished'))


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    date = datetime.fromisoformat(value)
    return date if date.tzinfo is not None else date.replace(tzinfo=timezone.utc)


def _status(queue, rq_id: str) -> str | None:
    """Don't infer job status from Redis LLEN; query RQ's own job record."""
    job = queue.fetch_job(rq_id)
    if job is None:
        return None
    state = job.get_status(refresh=True)
    return state.value if hasattr(state, 'value') else str(state)


def _cleanup_stage(job_id: str) -> None:
    path = AppPaths.from_environment().uploads_dir / 'staging' / (job_id + '.pdf')
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning('Could not remove staged file after terminal failure %s', path)


def reconcile_once(repo, queue, *, max_attempts: int = 3,
                   backoff_seconds: float = 2.0,
                   enqueue_grace_seconds: float = 10.0) -> dict:
    """One bounded reconciliation pass. Rerunning is safe for a single daemon.

    New retries are persisted *before* queueing, and a crashed producer can be
    recovered because queued rows with absent RQ deliveries are re-enqueued.
    """
    counts = {'examined': 0, 'planned_retries': 0, 'enqueued': 0, 'failed': 0, 'errors': 0}
    now = datetime.now(timezone.utc)
    pending_jobs = repo.pending()

    if any(job['status'] == 'running' for job in pending_jobs):
        # RQ 2.12's get_job_ids() defaults to cleanup=True. Its cleanup
        # expires abandoned jobs, moves them to FailedJobRegistry, and marks
        # them failed with AbandonedJobError. Simply calling get_status() on
        # the job would keep reporting stale 'started' if no other process
        # triggers registry cleanup (observed in a SIGKILL chaos test).
        #
        # Sweep BEFORE fetching each RQ job's status so this same pass can
        # observe 'failed' and plan a retry. No direct Redis mutations and no
        # guessing based on heartbeat timestamps: RQ owns expiration rules.
        try:
            queue.started_job_registry.get_job_ids()
        except Exception:
            counts['errors'] += 1
            logger.exception('RQ StartedJobRegistry cleanup failed; retrying next pass')

    for job in pending_jobs:
        counts['examined'] += 1
        jid = job['job_id']
        rq_id = job['rq_job_id'] or jid
        try:
            state = _status(queue, rq_id)
            if job['status'] == 'running':
                if state in FAILED_RQ or state is None:
                    # Missing Redis entry might mean a Redis flush. Do not guess
                    # that a *currently* active worker is dead until timeout.
                    if state is None:
                        started = _dt(job['started_at'])
                        if started is None or (now - started).total_seconds() < 360:
                            continue
                    retry_id = repo.plan_retry(jid, rq_id,
                                               f'RQ attempt {state or "missing"}',
                                               max_attempts=max_attempts,
                                               backoff_seconds=backoff_seconds)
                    if retry_id:
                        counts['planned_retries'] += 1
                        logger.warning('Recovering abandoned attempt job=%s old=%s new=%s',
                                       jid, rq_id, retry_id, extra={
                                           'event': 'ingestion_attempt_recovered',
                                           'job_id': jid, 'rq_job_id': retry_id,
                                       })
                    elif repo.get(jid)['status'] == 'failed':
                        counts['failed'] += 1
                        _cleanup_stage(jid)
                # An RQ started execution is *not* retried until RQ declares it
                # failed or the record has disappeared past the timeout grace.
                continue

            retry_at = _dt(job['retry_at'])
            if retry_at and retry_at > now:
                continue
            # If an RQ delivery exists, never enqueue a duplicate of that ID.
            if state in ACTIVE_RQ:
                continue
            if state in FAILED_RQ:
                repo.rotate_queued_delivery(jid, rq_id, f'RQ delivery {state}',
                                            max_attempts=max_attempts)
                if repo.get(jid)['status'] == 'failed':
                    counts['failed'] += 1
                    _cleanup_stage(jid)
                else:
                    counts['planned_retries'] += 1
                continue
            # No RQ job found: API may be between SQL commit and Redis enqueue.
            # Require grace on brand-new entries to avoid racing that API call.
            created = _dt(job['created_at'])
            if (created and job['attempts'] == 0 and rq_id == jid
                    and (now - created).total_seconds() < enqueue_grace_seconds):
                continue
            enqueue_delivery(queue, jid, rq_id)
            counts['enqueued'] += 1
            logger.info('Enqueued persisted job=%s delivery=%s', jid, rq_id, extra={
                'event': 'ingestion_delivery_enqueued', 'job_id': jid, 'rq_job_id': rq_id,
            })
        except Exception:
            counts['errors'] += 1
            logger.exception('Reconcile failed for job %s; will retry next pass', jid)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description='Repair abandoned async PDF ingestion jobs')
    parser.add_argument('--once', action='store_true', help='run one pass, then exit')
    args = parser.parse_args()
    configure_logging('reconciler')

    from redis import Redis
    from rq import Queue
    redis_conn = Redis.from_url(os.getenv('REDIS_URL', 'redis://redis:6379/0'))
    queue = Queue('marine-ingest', connection=redis_conn)
    engine = make_engine()
    repo = IngestionJobRepository(engine)
    interval = max(1, float(os.getenv('MARINE_RECONCILE_INTERVAL_SECONDS', '5')))
    try:
        while True:
            try:
                summary = reconcile_once(repo, queue,
                    max_attempts=int(os.getenv('MARINE_JOB_MAX_ATTEMPTS', '3')),
                    backoff_seconds=float(os.getenv('MARINE_JOB_BACKOFF_BASE', '2')))
                if not summary['errors']:
                    publish_reconciler_heartbeat(redis_conn)
                if summary['enqueued'] or summary['planned_retries'] or summary['failed']:
                    logger.info('reconciliation_completed', extra={'event': 'reconciliation_completed', **summary})
            except Exception:
                logger.exception('Reconciliation pass failed; retrying on next tick')
            if args.once:
                break
            time.sleep(interval)
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
