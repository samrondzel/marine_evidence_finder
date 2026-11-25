"""First async-ingestion slice: durable jobs, enqueue, separate worker, BM25 refresh."""
from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from marine_evidence.api import create_app
from marine_evidence.corpus_store import CorpusStore
from marine_evidence.db_models import Base
from marine_evidence.ingestion_job_repository import IngestionJobRepository
from marine_evidence.metadata_repository import UploadedDocumentRepository
from test_corpus_store import pdf_bytes, store  # noqa: F401 fixture


class FakeQueue:
    def __init__(self, fail=False):
        self.jobs = []
        self.fail = fail

    def enqueue(self, func, *args, **kwargs):
        if self.fail:
            raise ConnectionError('Redis is down')
        self.jobs.append((func, args, kwargs))


@pytest.fixture()
def engine(tmp_path):
    db_path = tmp_path / 'jobs-test.sqlite3'
    engine = create_engine(f'sqlite+pysqlite:///{db_path}')
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def open_pg_store(old, engine):
    return CorpusStore(base_chunks_path=old.uploads_dir.parent / 'base.jsonl',
                       base_papers_dir=old.base_papers_dir,
                       uploads_dir=old.uploads_dir,
                       metadata_repo=UploadedDocumentRepository(engine))


def test_job_repository_state_machine(engine):
    repo = IngestionJobRepository(engine)
    j = 'a' * 32
    assert repo.create(j, 'paper.pdf')['status'] == 'queued'
    assert repo.claim(j)
    assert not repo.claim(j)
    repo.succeed(j, 'U' + 'F' * 16, False)
    assert repo.get(j)['status'] == 'succeeded'
    assert repo.get(j)['source_id'] == 'U' + 'F' * 16
    repo.fail(j, 'must not overwrite success')
    assert repo.get(j)['status'] == 'succeeded'
    assert repo.get('b'*32) is None


def test_enqueue_status_and_worker_document_visible_without_restart(store, engine, monkeypatch):
    # Simulate two processes with separate CorpusStores against the same DB/files.
    from marine_evidence import ingestion_jobs
    job_repo = IngestionJobRepository(engine)
    queue = FakeQueue()
    api_store = open_pg_store(store, engine)
    monkeypatch.setattr(ingestion_jobs, 'make_engine', lambda: create_engine(str(engine.url)))
    monkeypatch.setenv('MARINE_BASE_CHUNKS_PATH', str(store.uploads_dir.parent / 'base.jsonl'))
    monkeypatch.setenv('MARINE_BASE_PAPERS_DIR', str(store.base_papers_dir))
    monkeypatch.setenv('MARINE_UPLOADS_DIR', str(store.uploads_dir))
    monkeypatch.setenv('MARINE_BASE_MANIFEST_PATH', str(store.uploads_dir.parent / 'not-present.json'))

    payload = pdf_bytes('The undersea mapping drone uses sonar and acoustic telemetry.')
    with TestClient(create_app(store=api_store, jobs_repository=job_repo, job_queue=queue)) as client:
        res = client.post('/ingestion-jobs', files={'file': ('drone.pdf', payload, 'application/pdf')})
        assert res.status_code == 202, res.text
        job_id = res.json()['job_id']
        assert len(job_id) == 32
        assert res.json()['status_url'] == '/ingestion-jobs/' + job_id
        assert queue.jobs[0][0] == 'marine_evidence.ingestion_jobs.process_ingestion_job'
        assert queue.jobs[0][1] == (job_id,)
        assert client.get('/ingestion-jobs/' + job_id).json()['status'] == 'queued'
        assert client.post('/search', json={'question': 'sonar drone mapping'}).json()['hits'] == []

        result = ingestion_jobs.process_ingestion_job(job_id)
        assert not result['duplicate']
        job = client.get('/ingestion-jobs/' + job_id).json()
        assert job['status'] == 'succeeded'
        assert job['source_id'] == result['source_id']
        assert not list((store.uploads_dir / 'staging').glob('*.pdf'))
        assert any(d['source_id'] == result['source_id'] for d in client.get('/documents').json()['documents'])
        hits = client.post('/search', json={'question': 'sonar drone mapping'}).json()['hits']
        assert hits and hits[0]['source_id'] == result['source_id']
        assert client.get(f'/documents/{result["source_id"]}/pdf').status_code == 200
        # Process-local index stays current after a second API read.
        assert api_store.chunk_count > 1
        assert client.get('/ingestion-jobs/bad-id').status_code == 404
        assert client.get('/ingestion-jobs/' + 'f'*32).status_code == 404


def test_queue_failure_marks_job_failed_and_cleans_staging(store, engine):
    repo = IngestionJobRepository(engine)
    with TestClient(create_app(store=open_pg_store(store, engine),
                               jobs_repository=repo, job_queue=FakeQueue(fail=True))) as client:
        res = client.post('/ingestion-jobs', files={'file': ('paper.pdf', pdf_bytes(), 'application/pdf')})
        assert res.status_code == 503
        assert not list((store.uploads_dir / 'staging').glob('*.pdf'))
        from sqlalchemy.orm import Session
        from sqlalchemy import select
        from marine_evidence.db_models import IngestionJob
        with Session(engine) as session:
            jobs = session.scalars(select(IngestionJob)).all()
            assert len(jobs) == 1 and jobs[0].status == 'failed'


def test_bad_upload_rejected_before_queue(store, engine):
    queue = FakeQueue()
    with TestClient(create_app(store=open_pg_store(store, engine),
                               jobs_repository=IngestionJobRepository(engine), job_queue=queue)) as client:
        assert client.post('/ingestion-jobs', files={'file': ('wrong.txt', b'abc')}).status_code == 422
        assert client.post('/ingestion-jobs', files={'file': ('bad.pdf', b'abc')}).status_code == 422
        assert queue.jobs == []


def test_worker_reports_invalid_pdf_failed_job(store, engine, monkeypatch):
    from marine_evidence import ingestion_jobs
    repo = IngestionJobRepository(engine)
    j = 'c' * 32
    repo.create(j, 'unreadable.pdf')
    staged = store.uploads_dir / 'staging' / (j + '.pdf')
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b'%PDF-not a valid document')
    monkeypatch.setattr(ingestion_jobs, 'make_engine', lambda: create_engine(str(engine.url)))
    monkeypatch.setenv('MARINE_BASE_CHUNKS_PATH', str(store.uploads_dir.parent / 'base.jsonl'))
    monkeypatch.setenv('MARINE_BASE_PAPERS_DIR', str(store.base_papers_dir))
    monkeypatch.setenv('MARINE_UPLOADS_DIR', str(store.uploads_dir))
    with pytest.raises(Exception):
        ingestion_jobs.process_ingestion_job(j)
    assert repo.get(j)['status'] == 'failed'
    assert not any(d['uploaded'] for d in open_pg_store(store, engine).list_documents())


def test_alembic_upgrade_creates_jobs_schema(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / 'alembic.sqlite3'
    monkeypatch.setenv('DATABASE_URL', 'sqlite+pysqlite:///' + str(db_path))
    config = Config(str(root / 'alembic.ini'))
    config.set_main_option('script_location', str(root / 'migrations'))
    command.upgrade(config, 'head')
    engine = create_engine('sqlite+pysqlite:///' + str(db_path))
    try:
        from sqlalchemy import inspect, text
        assert set(['ingestion_jobs', 'uploaded_documents', 'alembic_version']).issubset(inspect(engine).get_table_names())
        with engine.connect() as conn:
            assert conn.scalar(text('SELECT version_num FROM alembic_version')) == '0003_ingestion_reliability'
    finally:
        engine.dispose()


def test_compose_jobs_adds_worker_without_exposing_redis():
    root = Path(__file__).resolve().parents[1]
    config = (root / 'compose.jobs.yaml').read_text(encoding='utf-8')
    assert 'MARINE_ASYNC_INGESTION:' in config
    assert 'marine-ingest' in config and 'redis:7.4-alpine' in config
    assert 'ports:' not in config
    assert 'requirements-jobs.txt' in (root / 'Dockerfile.jobs').read_text()


def test_retry_adopts_matching_orphan_files_after_crash(store, engine):
    """Kill between file writes and metadata insert: retry can adopt matching files."""
    import json
    from marine_evidence.corpus_store import extract_uploaded_pdf

    data = pdf_bytes('Humpback whales communicate with complex acoustic signals.')
    record, rows = extract_uploaded_pdf(data, 'orphan.pdf')
    sid = record['source_id']
    pdf = store.uploads_dir / 'pdfs' / f'{sid}.pdf'
    chunks = store.uploads_dir / 'chunks' / f'{sid}.jsonl'
    pdf.parent.mkdir(parents=True, exist_ok=True)
    chunks.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(data)
    chunks.write_bytes((''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in rows)).encode('utf-8'))

    first_store = open_pg_store(store, engine)
    document, is_duplicate = first_store.upload_pdf(data, 'orphan.pdf')
    assert document['source_id'] == sid
    assert is_duplicate is False
    second_store = open_pg_store(store, engine)
    again, duplicate = second_store.upload_pdf(data, 'orphan.pdf')
    assert again['source_id'] == sid and duplicate is True
    assert len([d for d in second_store.list_documents() if d['source_id'] == sid]) == 1
