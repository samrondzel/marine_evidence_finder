"""Sprint 2 state-machine and reconciliation tests; no live Redis needed."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import Session

from marine_evidence.db_models import Base, IngestionJob
from marine_evidence.ingestion_job_repository import IngestionJobRepository
from marine_evidence.job_reconciler import reconcile_once


class FakeRQJob:
    def __init__(self, status):
        self.status = status

    def get_status(self, refresh=True):
        return self.status


class FakeStartedRegistry:
    """Model RQ 2.12: get_job_ids() sweeps expired started deliveries."""

    def __init__(self, queue):
        self.queue = queue
        self.expired = set()
        self.cleanup_calls = 0

    def get_job_ids(self):
        self.cleanup_calls += 1
        for rq_id in self.expired:
            if self.queue.jobs.get(rq_id) == 'started':
                self.queue.jobs[rq_id] = 'failed'
        return [rq_id for rq_id, status in self.queue.jobs.items()
                if status == 'started']


class FakeRQ:
    def __init__(self):
        self.jobs = {}
        self.submitted = []
        self.started_job_registry = FakeStartedRegistry(self)

    def fetch_job(self, rq_id):
        return FakeRQJob(self.jobs[rq_id]) if rq_id in self.jobs else None

    def enqueue(self, func, durable_id, **kwargs):
        delivery = kwargs['job_id']
        self.submitted.append((func, durable_id, delivery, kwargs))
        self.jobs[delivery] = 'queued'


def make_repo(tmp_path):
    engine = create_engine('sqlite+pysqlite:///' + str(tmp_path / 'db.sqlite'))
    Base.metadata.create_all(engine)
    return engine, IngestionJobRepository(engine)


def test_abandoned_running_requeues_and_completes(tmp_path):
    engine, repo = make_repo(tmp_path)
    q = FakeRQ()
    jid = 'a' * 32
    repo.create(jid, 'sample.pdf')
    assert repo.claim(jid)
    assert repo.get(jid)['attempts'] == 1
    q.jobs[jid] = 'failed'  # RQ cleanup after SIGKILL
    outcome = reconcile_once(repo, q, backoff_seconds=0)
    assert outcome['planned_retries'] == 1
    next_id = repo.get(jid)['rq_job_id']
    assert next_id == jid + '-a2'
    assert repo.get(jid)['status'] == 'queued'
    assert not repo.claim(jid, jid), 'Old RQ attempt must never claim newer retry'
    outcome = reconcile_once(repo, q, backoff_seconds=0)
    assert outcome['enqueued'] == 1
    assert q.submitted[-1][2] == next_id
    assert repo.claim(jid, next_id)
    assert repo.get(jid)['attempts'] == 2
    try:
        repo.succeed(jid, 'U' + 'F' * 16, False, jid)
    except RuntimeError:
        pass
    else:
        raise AssertionError('Stale attempts must not finish newer work')
    repo.succeed(jid, 'U' + 'F' * 16, True, next_id)
    assert repo.get(jid)['status'] == 'succeeded'
    q.jobs[next_id] = 'finished'
    assert reconcile_once(repo, q)['planned_retries'] == 0
    engine.dispose()


def test_retry_budget_exhausted_and_terminal_success_protected(tmp_path):
    engine, repo = make_repo(tmp_path)
    q = FakeRQ()
    jid = 'b' * 32
    repo.create(jid, 'sample.pdf')
    assert repo.claim(jid)
    q.jobs[jid] = 'failed'
    reconcile_once(repo, q, max_attempts=2, backoff_seconds=0)
    reconcile_once(repo, q, max_attempts=2, backoff_seconds=0)
    delivery = repo.get(jid)['rq_job_id']
    assert repo.claim(jid, delivery)
    q.jobs[delivery] = 'failed'
    outcome = reconcile_once(repo, q, max_attempts=2, backoff_seconds=0)
    assert outcome['failed'] == 1
    assert repo.get(jid)['status'] == 'failed'
    assert not repo.claim(jid, delivery)
    engine.dispose()


def test_redis_enqueue_gap_eventually_repairs_queued(tmp_path):
    engine, repo = make_repo(tmp_path)
    q = FakeRQ()
    jid = 'c' * 32
    repo.create(jid, 'orphan.pdf')  # DB commit succeeded but Redis enqueue lost
    outcome = reconcile_once(repo, q, enqueue_grace_seconds=0)
    assert outcome['enqueued'] == 1
    assert q.submitted[0][2] == jid
    assert reconcile_once(repo, q, enqueue_grace_seconds=0)['enqueued'] == 0
    engine.dispose()


def test_first_rq_delivery_failed_before_claim_can_rotate(tmp_path):
    engine, repo = make_repo(tmp_path)
    q = FakeRQ()
    jid = 'd' * 32
    repo.create(jid, 'no-claim.pdf')
    q.jobs[jid] = 'failed'
    assert reconcile_once(repo, q, enqueue_grace_seconds=0)['planned_retries'] == 1
    assert repo.get(jid)['status'] == 'queued'
    assert repo.get(jid)['rq_job_id'] != jid
    assert reconcile_once(repo, q, enqueue_grace_seconds=0)['enqueued'] == 1
    engine.dispose()


def test_0003_migration_backfills_old_running_job(tmp_path, monkeypatch):
    db = tmp_path / 'migrate.sqlite'
    monkeypatch.setenv('DATABASE_URL', 'sqlite+pysqlite:///' + str(db))
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / 'alembic.ini'))
    cfg.set_main_option('script_location', str(root / 'migrations'))
    command.upgrade(cfg, '0002_ingestion_jobs')
    engine = create_engine('sqlite+pysqlite:///' + str(db))
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO ingestion_jobs(job_id,filename,status,created_at,started_at) "
                          "VALUES (:id,'old.pdf','running','2026-11-18 10:00:00', '2026-11-18 10:01:00')"),
                     {'id': 'e' * 32})
    command.upgrade(cfg, 'head')
    with engine.connect() as conn:
        row = conn.execute(text('SELECT attempts,rq_job_id,status FROM ingestion_jobs WHERE job_id=:id'),
                           {'id': 'e' * 32}).one()
        assert row == (1, 'e' * 32, 'running')
        assert 'ix_ingestion_jobs_status' in {x['name'] for x in inspect(engine).get_indexes('ingestion_jobs')}
        assert conn.scalar(text('SELECT version_num FROM alembic_version')) == '0003_ingestion_reliability'
    engine.dispose()


def test_backoff_and_rq_still_started_does_not_requeue(tmp_path):
    engine, repo = make_repo(tmp_path)
    q = FakeRQ()
    jid = 'f' * 32
    repo.create(jid, 'slow.pdf')
    assert repo.claim(jid)
    q.jobs[jid] = 'started'
    assert reconcile_once(repo, q)['planned_retries'] == 0
    assert repo.get(jid)['status'] == 'running'
    q.jobs[jid] = 'failed'
    assert reconcile_once(repo, q, backoff_seconds=300)['planned_retries'] == 1
    assert repo.get(jid)['retry_at'] is not None
    assert reconcile_once(repo, q)['enqueued'] == 0, 'Retry backoff is respected'
    engine.dispose()


def test_preclaim_failures_consume_retry_budget(tmp_path):
    engine, repo = make_repo(tmp_path)
    q = FakeRQ()
    jid = '1' * 32
    repo.create(jid, 'bad-import.pdf')
    for i in range(2):
        active = repo.get(jid)['rq_job_id']
        q.jobs[active] = 'failed'
        assert reconcile_once(repo, q, max_attempts=2)['planned_retries'] == 1
    current = repo.get(jid)['rq_job_id']
    assert repo.get(jid)['attempts'] == 2
    q.jobs[current] = 'failed'
    assert reconcile_once(repo, q, max_attempts=2)['failed'] == 1
    assert repo.get(jid)['status'] == 'failed'
    engine.dispose()


def test_reconciler_cleans_expired_started_registry_without_manual_intervention(tmp_path):
    """Regression for real SIGKILL: RQ STARTED until get_job_ids() sweeps it."""
    engine, repo = make_repo(tmp_path)
    q = FakeRQ()
    jid = '2' * 32
    repo.create(jid, 'abandoned.pdf')
    assert repo.claim(jid)
    q.jobs[jid] = 'started'  # stale Redis status left after SIGKILL
    q.started_job_registry.expired.add(jid)

    outcome = reconcile_once(repo, q, backoff_seconds=0)
    assert q.started_job_registry.cleanup_calls == 1
    assert q.jobs[jid] == 'failed', 'RQ native registry sweep marks orphan as failed'
    assert outcome['planned_retries'] == 1, 'Retry planned on the very same pass'
    assert repo.get(jid)['status'] == 'queued'
    next_delivery = repo.get(jid)['rq_job_id']
    assert next_delivery == jid + '-a2'

    # Reconciler enqueues the new delivery on its next normal pass.
    outcome = reconcile_once(repo, q, backoff_seconds=0)
    assert outcome['enqueued'] == 1
    assert q.submitted[-1][2] == next_delivery
    assert repo.claim(jid, next_delivery)
    repo.succeed(jid, 'U' + '7' * 16, False, next_delivery)
    assert repo.get(jid)['status'] == 'succeeded'
    engine.dispose()


def test_registry_cleanup_does_not_requeue_healthy_started_delivery(tmp_path):
    engine, repo = make_repo(tmp_path)
    q = FakeRQ()
    jid = '3' * 32
    repo.create(jid, 'healthy-worker.pdf')
    assert repo.claim(jid)
    q.jobs[jid] = 'started'  # active: not marked expired

    for expected_calls in (1, 2, 3):
        outcome = reconcile_once(repo, q)
        assert q.started_job_registry.cleanup_calls == expected_calls
        assert outcome['planned_retries'] == 0
        assert outcome['enqueued'] == 0
        assert repo.get(jid)['status'] == 'running'
        assert repo.get(jid)['attempts'] == 1
    engine.dispose()
