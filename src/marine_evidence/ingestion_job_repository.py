"""PostgreSQL-backed ingestion state machine; Redis is only a delivery mechanism.

An attempt is owned by one RQ delivery id. CAS updates prevent older workers from
claiming or finishing newer attempts. A queued retry is durable before enqueue.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .db_models import IngestionJob


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize(job: IngestionJob) -> dict:
    def iso(value):
        return value.isoformat(timespec='seconds') if value is not None else None

    return {
        'job_id': job.job_id, 'filename': job.filename, 'status': job.status,
        'source_id': job.source_id, 'duplicate': job.duplicate, 'error': job.error,
        'created_at': iso(job.created_at), 'started_at': iso(job.started_at),
        'finished_at': iso(job.finished_at), 'attempts': job.attempts,
        'rq_job_id': job.rq_job_id, 'retry_at': iso(job.retry_at),
    }


class IngestionJobRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def create(self, job_id: str, filename: str) -> dict:
        with Session(self.engine) as session, session.begin():
            session.add(IngestionJob(job_id=job_id, filename=filename, status='queued',
                                     created_at=_now(), attempts=0, rq_job_id=job_id))
        return self.get(job_id)

    def get(self, job_id: str) -> dict | None:
        with Session(self.engine) as session:
            row = session.get(IngestionJob, job_id)
            return _serialize(row) if row else None

    def pending(self) -> list[dict]:
        """Scan only unfinished tasks; a single reconciler process is expected."""
        with Session(self.engine) as session:
            rows = session.scalars(select(IngestionJob).where(
                IngestionJob.status.in_(['queued', 'running']))).all()
            return [_serialize(row) for row in rows]

    def observability_snapshot(self) -> dict:
        """Aggregated job state only: no job_id / filename / document contents.

        SQL aggregation keeps monitoring cost bounded as job history grows.
        The running timestamp is the *oldest current attempt* start time.
        """
        with Session(self.engine) as session:
            counts = dict(session.execute(
                select(IngestionJob.status, func.count(IngestionJob.job_id))
                .group_by(IngestionJob.status)
            ).all())
            oldest_running = session.scalar(select(func.min(IngestionJob.started_at)).where(
                IngestionJob.status == 'running'))
        return {'counts': counts, 'oldest_running': oldest_running}

    def claim(self, job_id: str, rq_job_id: str | None = None) -> bool:
        """Atomically claim exactly one queued attempt, never a previous delivery."""
        delivery_id = rq_job_id or job_id
        with Session(self.engine) as session, session.begin():
            row = session.scalar(select(IngestionJob).where(IngestionJob.job_id == job_id).with_for_update())
            if row is None or row.status != 'queued' or row.rq_job_id != delivery_id:
                return False
            # CAS conditions on both status and delivery id.
            result = session.execute(update(IngestionJob).where(
                IngestionJob.job_id == job_id, IngestionJob.status == 'queued',
                IngestionJob.rq_job_id == delivery_id,
            ).values(status='running', attempts=IngestionJob.attempts + 1,
                     started_at=_now(), retry_at=None, error=None))
            return result.rowcount == 1

    def succeed(self, job_id: str, source_id: str, duplicate: bool,
                rq_job_id: str | None = None) -> None:
        delivery_id = rq_job_id or job_id
        with Session(self.engine) as session, session.begin():
            result = session.execute(update(IngestionJob).where(
                IngestionJob.job_id == job_id, IngestionJob.status == 'running',
                IngestionJob.rq_job_id == delivery_id,
            ).values(status='succeeded', source_id=source_id,
                     duplicate=duplicate, finished_at=_now(), error=None))
            if result.rowcount != 1:
                raise RuntimeError('Attempt lost ownership before recording success')

    def fail(self, job_id: str, message: str, rq_job_id: str | None = None) -> bool:
        """Terminal failure, conditional on owning the current delivery."""
        with Session(self.engine) as session, session.begin():
            conditions = [IngestionJob.job_id == job_id,
                          IngestionJob.status.in_(['queued', 'running'])]
            if rq_job_id is not None:
                conditions.append(IngestionJob.rq_job_id == rq_job_id)
            result = session.execute(update(IngestionJob).where(*conditions).values(
                status='failed', error=message[:300], finished_at=_now(), retry_at=None))
            return result.rowcount == 1

    def rotate_queued_delivery(self, job_id: str, rq_job_id: str, message: str,
                               *, max_attempts: int = 3) -> bool:
        """Replace an RQ ID that failed before it could claim a queued task."""
        with Session(self.engine) as session, session.begin():
            row = session.scalar(select(IngestionJob).where(IngestionJob.job_id == job_id).with_for_update())
            if row is None or row.status != 'queued' or row.rq_job_id != rq_job_id:
                return False
            if row.attempts >= max_attempts:
                row.status = 'failed'
                row.error = ('Delivery failures exhausted: ' + message)[:300]
                row.finished_at = _now()
                return True
            # Count failures even if the worker died before reaching claim().
            row.attempts += 1
            # Use a unique id even when no worker ever claimed the previous one.
            # An opaque UUID avoids collision with pre-existing delivery attempts.
            from uuid import uuid4
            row.rq_job_id = f'{job_id}-r{uuid4().hex[:12]}'
            row.retry_at = _now()
            row.error = ('Delivery retry: ' + message)[:300]
            return True

    def plan_retry(self, job_id: str, rq_job_id: str, message: str,
                   *, max_attempts: int = 3, backoff_seconds: float = 2.0) -> str | None:
        """Persist retry intent first; reconciler enqueues it when due.

        The next RQ ID is deterministic and different from earlier failed IDs.
        If the attempt budget is exhausted, persist terminal failure instead.
        """
        with Session(self.engine) as session, session.begin():
            row = session.scalar(select(IngestionJob).where(IngestionJob.job_id == job_id).with_for_update())
            if row is None or row.status != 'running' or row.rq_job_id != rq_job_id:
                return None
            attempts = max(row.attempts, 1)  # legacy running rows were backfilled
            if attempts >= max_attempts:
                row.status = 'failed'
                row.error = ('Retry budget exhausted: ' + message)[:300]
                row.finished_at = _now()
                row.retry_at = None
                return None
            next_id = f'{job_id}-a{attempts + 1}'
            row.status = 'queued'
            row.rq_job_id = next_id
            row.retry_at = _now() + timedelta(seconds=backoff_seconds * 2 ** (attempts - 1))
            row.error = ('Retry scheduled: ' + message)[:300]
            row.started_at = None
            row.finished_at = None
            return next_id
