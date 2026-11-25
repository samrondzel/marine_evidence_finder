"""RQ worker: retryable ingestion with durable attempt ownership in PostgreSQL."""
from __future__ import annotations

import logging
import os
import re
import time

from .config import AppPaths
from .observability import configure_logging
from .corpus_store import CorpusStore, DocumentError
from .db_connection import make_engine
from .ingestion_job_repository import IngestionJobRepository
from .metadata_repository import UploadedDocumentRepository

logger = logging.getLogger(__name__)
JOB_ID_RE = re.compile(r'^[a-f0-9]{32}$')


def _current_delivery_id(job_id: str) -> str:
    # Direct function execution by tests does not have an RQ current job.
    try:
        from rq import get_current_job
        current = get_current_job()
        return current.id if current is not None else job_id
    except ImportError:
        return job_id


def process_ingestion_job(job_id: str) -> dict:
    if not JOB_ID_RE.fullmatch(job_id):
        raise ValueError('Invalid job ID')
    delivery_id = _current_delivery_id(job_id)
    configure_logging('worker')
    engine = make_engine()
    try:
        jobs = IngestionJobRepository(engine)
        if not jobs.claim(job_id, delivery_id):
            raise RuntimeError('Attempt is stale, already claimed, or missing')
        attempt_start = time.perf_counter()
        logger.info('ingestion_attempt_started', extra={
            'event': 'ingestion_attempt_started', 'job_id': job_id, 'rq_job_id': delivery_id,
        })
        # Opt-in fault injection only. Zero by default; no sleep in real work.
        chaos_pause = float(os.getenv('MARINE_CHAOS_PAUSE_AFTER_CLAIM_SECONDS', '0'))
        if chaos_pause > 0:
            logger.warning('CHAOS pause after claim job_id=%s for %.1f s', job_id, chaos_pause)
            time.sleep(chaos_pause)
        paths = AppPaths.from_environment()
        staged = paths.uploads_dir / 'staging' / (job_id + '.pdf')
        try:
            job = jobs.get(job_id)
            if job is None:
                raise RuntimeError('Claimed job vanished')
            payload = staged.read_bytes()
            store = CorpusStore(base_chunks_path=paths.base_chunks_path,
                                base_papers_dir=paths.base_papers_dir,
                                uploads_dir=paths.uploads_dir,
                                base_manifest_path=paths.base_manifest_path,
                                metadata_repo=UploadedDocumentRepository(engine))
            document, duplicate = store.upload_pdf(payload, job['filename'])
            jobs.succeed(job_id, document['source_id'], duplicate, delivery_id)
        except Exception as exc:
            logger.exception('ingestion_attempt_error', extra={
                'event': 'ingestion_attempt_error', 'job_id': job_id, 'rq_job_id': delivery_id,
                'duration_ms': round((time.perf_counter() - attempt_start) * 1000, 2),
            })
            try:
                if isinstance(exc, DocumentError) or isinstance(exc, FileNotFoundError):
                    # Damaged PDFs / missing staging file cannot succeed by retrying.
                    jobs.fail(job_id, str(exc) if isinstance(exc, DocumentError)
                              else 'Staged PDF missing', delivery_id)
                else:
                    jobs.plan_retry(job_id, delivery_id, 'Processing error',
                                    max_attempts=int(os.getenv('MARINE_JOB_MAX_ATTEMPTS', '3')),
                                    backoff_seconds=float(os.getenv('MARINE_JOB_BACKOFF_BASE', '2')))
            except Exception:
                # If PostgreSQL is temporarily down, RQ marks this attempt failed;
                # the reconciler will retry it when PostgreSQL is available.
                logger.exception('Could not persist attempt outcome job_id=%s', job_id)
            # Cleanup only for terminal failures; keep staged PDF for retries.
            try:
                if jobs.get(job_id)['status'] == 'failed':
                    staged.unlink(missing_ok=True)
            except Exception:
                logger.warning('Could not check or clean terminal staging for %s', job_id)
            raise
        # Staging removal must never turn an already successful task into an RQ failure.
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            logger.warning('Could not remove staged file after success: %s', staged)
        logger.info('ingestion_attempt_succeeded', extra={
            'event': 'ingestion_attempt_succeeded', 'job_id': job_id,
            'rq_job_id': delivery_id, 'source_id': document['source_id'],
            'duration_ms': round((time.perf_counter() - attempt_start) * 1000, 2),
        })
        return {'source_id': document['source_id'], 'duplicate': duplicate}
    finally:
        engine.dispose()
