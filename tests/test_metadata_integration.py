"""Postgres metadata integration tested with SQLite, avoiding external services."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from marine_evidence.api import create_app
from marine_evidence.backfill_metadata import plan_backfill, verified_legacy_records
from marine_evidence.corpus_store import CorpusStore, MetadataStoreError
from marine_evidence.db_models import Base
from marine_evidence.metadata_repository import MetadataConflict, UploadedDocumentRepository
from test_corpus_store import pdf_bytes, store  # noqa: F401  fixture


@pytest.fixture()
def repo():
    engine = create_engine('sqlite+pysqlite:///:memory:',
                           connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    result = UploadedDocumentRepository(engine)
    yield result
    engine.dispose()


def reopen(old, repo):
    return CorpusStore(base_chunks_path=old.uploads_dir.parent/'base.jsonl',
                       base_papers_dir=old.base_papers_dir,
                       uploads_dir=old.uploads_dir, metadata_repo=repo)


def test_backfill_legacy_and_restart_then_db_is_source_of_truth(store, repo):
    original, _ = store.upload_pdf(pdf_bytes(), 'porpoise.pdf')
    records = verified_legacy_records(store.uploads_dir)
    assert len(records) == 1
    assert plan_backfill(repo, records) == (1, 0)
    assert repo.backfill(records) == (1, 0)
    assert repo.backfill(records) == (0, 1)  # Idempotent, not duplicate rows
    assert plan_backfill(repo, records) == (0, 1)

    pg = reopen(store, repo)
    assert pg.chunk_count == store.chunk_count
    assert pg.search('Porpoises stopped feeding')[0]['source_id'] == original['source_id']
    assert len(pg.list_documents()) == 2
    old_registry = pg.registry_path.read_bytes()

    # A DIFFERENT PDF upload must be persisted in PostgreSQL, NOT legacy JSON.
    second_blob = pdf_bytes('Robots in the sea map coral reef habitats using cameras.')
    second, duplicate = pg.upload_pdf(second_blob, 'robotics.pdf')
    assert not duplicate
    assert pg.registry_path.read_bytes() == old_registry
    assert len(repo.list_records()) == 2

    restarted = reopen(pg, repo)
    assert restarted.search('coral reef habitats')[0]['source_id'] == second['source_id']
    assert restarted.delete_upload(original['source_id'])
    assert len(repo.list_records()) == 1
    assert restarted.registry_path.read_bytes() == old_registry
    restarted_again = reopen(restarted, repo)
    assert {d['source_id'] for d in restarted_again.list_documents()} == {'P01', second['source_id']}
    assert not restarted_again.delete_upload(original['source_id'])


def test_postgres_upload_db_error_rolls_back_files_index_and_memory(store, repo, monkeypatch):
    pg = reopen(store, repo)
    baseline = pg.chunk_count
    def broken_insert(record):
        raise OSError('simulated DB outage')
    monkeypatch.setattr(repo, 'insert', broken_insert)
    with pytest.raises(MetadataStoreError, match='commit failed or was uncertain'):
        pg.upload_pdf(pdf_bytes(), 'new.pdf')
    assert pg.chunk_count == baseline
    assert not pg.list_documents()[-1].get('uploaded')
    assert not list(pg.pdf_dir.glob('*.pdf'))
    assert not list(pg.chunks_dir.glob('*.jsonl'))
    assert repo.list_records() == []


def test_postgres_delete_db_error_preserves_document(store, repo, monkeypatch):
    pg = reopen(store, repo)
    rec, _ = pg.upload_pdf(pdf_bytes(), 'new.pdf')
    baseline = pg.chunk_count
    def broken_delete(source_id):
        raise OSError('simulated DB outage')
    monkeypatch.setattr(repo, 'delete', broken_delete)
    with pytest.raises(MetadataStoreError, match='could not be committed'):
        pg.delete_upload(rec['source_id'])
    assert pg.chunk_count == baseline
    assert pg.pdf_path(rec['source_id'])[0].is_file()
    assert len(repo.list_records()) == 1


def test_backfill_refuses_corrupt_pdf_without_db_mutation(store, repo):
    rec, _ = store.upload_pdf(pdf_bytes(), 'new.pdf')
    pdf = store.pdf_dir / (rec['source_id'] + '.pdf')
    pdf.write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='SHA-256 mismatch'):
        verified_legacy_records(store.uploads_dir)
    assert repo.list_records() == []


def test_backfill_conflict_rolls_back_entire_batch(store, repo):
    original, _ = store.upload_pdf(pdf_bytes(), 'first.pdf')
    records = verified_legacy_records(store.uploads_dir)
    altered = dict(records[0], filename='unrelated.pdf')
    assert repo.backfill(records) == (1, 0)
    with pytest.raises(MetadataConflict, match='Conflicting'):
        repo.backfill([altered])
    assert len(repo.list_records()) == 1
    assert repo.list_records()[0]['filename'] == original['filename']


def test_api_pg_lifespan_upload_and_readiness(store, repo, monkeypatch):
    from marine_evidence import db_connection
    monkeypatch.setattr(db_connection, 'make_engine', lambda: repo.engine)
    monkeypatch.setenv('MARINE_METADATA_BACKEND', 'postgres')
    monkeypatch.setenv('MARINE_BASE_CHUNKS_PATH', str(store.uploads_dir.parent/'base.jsonl'))
    monkeypatch.setenv('MARINE_BASE_PAPERS_DIR', str(store.base_papers_dir))
    monkeypatch.setenv('MARINE_UPLOADS_DIR', str(store.uploads_dir))
    # Engine.dispose() is safe at end of lifespan, but SQLite StaticPool will then
    # lose its in-memory database. Test while client is active only.
    with TestClient(create_app(root=store.uploads_dir.parent)) as client:
        assert client.get('/health/ready').json()['status'] == 'ready'
        uploaded = client.post('/documents', files={'file': ('new.pdf', pdf_bytes(), 'application/pdf')})
        assert uploaded.status_code == 201, uploaded.text
        assert len(repo.list_records()) == 1
        assert not (store.uploads_dir/'registry.json').exists()
        monkeypatch.setattr(client.app.state.store.metadata_repo, 'ping',
                            lambda: (_ for _ in ()).throw(ConnectionError('DB offline')))
        assert client.get('/health/ready').status_code == 503


def test_metadata_compose_config_and_dockerfile_exist():
    root = Path(__file__).resolve().parents[1]
    config = (root/'compose.metadata.yaml').read_text()
    docker = (root/'Dockerfile.metadata').read_text()
    assert 'MARINE_METADATA_BACKEND: postgres' in config
    assert 'PGPASSWORD:' in config and 'dockerfile: Dockerfile.metadata' in config
    assert '-r requirements-db.txt' in docker
    assert 'USER marine' in docker


def test_ambiguous_db_commit_keeps_files_for_recovery(store, repo, monkeypatch):
    pg = reopen(store, repo)
    monkeypatch.setattr(repo, 'insert', lambda record: (_ for _ in ()).throw(ConnectionError('lost ACK')))
    monkeypatch.setattr(repo, 'list_records', lambda: (_ for _ in ()).throw(ConnectionError('offline')))
    with pytest.raises(MetadataStoreError, match='uncertain'):
        pg.upload_pdf(pdf_bytes(), 'new.pdf')
    # Unknown DB outcome: never delete a file that could be referenced by a committed row.
    assert len(list(pg.pdf_dir.glob('*.pdf'))) == 1
    assert len(list(pg.chunks_dir.glob('*.jsonl'))) == 1
    assert pg.chunk_count == 1
