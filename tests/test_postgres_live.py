"""Opt-in integration tests against a DEDICATED PostgreSQL *_test database.

These tests never connect to the regular Marine Evidence database. They are
skipped unless MARINE_TEST_DATABASE_URL is explicitly set, and reject any URL
that isn't a local PostgreSQL test database. The schema must be migrated with
Alembic before running these tests (the CI workflow does this).
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marine_evidence.corpus_store import CorpusStore
from marine_evidence.db_models import UploadedDocument
from marine_evidence.metadata_repository import MetadataConflict, UploadedDocumentRepository
from test_corpus_store import pdf_bytes, store  # noqa: F401 - local fixture


def validate_test_database_url(raw: str) -> str:
    """Do not accidentally point destructive tests at development/production DB."""
    parsed = make_url(raw)
    if parsed.get_backend_name() != 'postgresql':
        raise ValueError('Live DB tests require PostgreSQL')
    if not (parsed.database or '').endswith('_test'):
        raise ValueError('Live DB tests require a database name ending in _test')
    if parsed.host not in {'127.0.0.1', 'localhost'}:
        raise ValueError('Live DB tests require a local PostgreSQL instance')
    return raw


def test_database_url_guard_rejects_non_test_database():
    with pytest.raises(ValueError, match='ending in _test'):
        validate_test_database_url('postgresql+psycopg://u:p@127.0.0.1:5433/marine_evidence')


def test_database_url_guard_rejects_nonlocal_host():
    with pytest.raises(ValueError, match='local PostgreSQL'):
        validate_test_database_url('postgresql+psycopg://u:p@remote.example:5432/marine_evidence_test')


@pytest.fixture(scope='module')
def pg_engine():
    raw = os.environ.get('MARINE_TEST_DATABASE_URL')
    if not raw:
        pytest.skip('Set MARINE_TEST_DATABASE_URL to opt into real PostgreSQL tests')
    url = validate_test_database_url(raw)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            actual_name = connection.scalar(text('SELECT current_database()'))
            if not str(actual_name).endswith('_test'):
                raise RuntimeError(f'Refusing non-test PostgreSQL database: {actual_name}')
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def pg_repo(pg_engine):
    return UploadedDocumentRepository(pg_engine)


def document_record() -> dict:
    key = uuid4().hex
    return {
        'source_id': 'U' + key[:16].upper(),
        'sha256': hashlib.sha256(key.encode('ascii')).hexdigest(),
        'filename': 'integration.pdf',
        'title': 'PostgreSQL test document',
        'doi': '',
        'pages': 2,
        'chunks': 3,
        'added_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'uploaded': True,
    }


def test_alembic_migration_was_applied(pg_engine):
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    with pg_engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == expected_head
        assert connection.scalar(text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'ingestion_jobs')")) is True
        assert connection.scalar(text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'uploaded_documents')")) is True


def test_repository_roundtrip_persists_across_connections(pg_repo, pg_engine):
    record = document_record()
    try:
        pg_repo.insert(record)
        restarted_repo = UploadedDocumentRepository(pg_engine)
        restored = next(row for row in restarted_repo.list_records()
                        if row['source_id'] == record['source_id'])
        assert restored['filename'] == record['filename']
        assert restored['sha256'] == record['sha256']
        assert restored['pages'] == 2
        assert restarted_repo.delete(record['source_id'])
        assert not restarted_repo.delete(record['source_id'])
    finally:
        pg_repo.delete(record['source_id'])


def test_postgres_enforces_unique_sha_and_positive_counts(pg_repo, pg_engine):
    record = document_record()
    try:
        pg_repo.insert(record)
        other = document_record()
        other['sha256'] = record['sha256']
        with pytest.raises(IntegrityError):
            pg_repo.insert(other)
        assert all(row['source_id'] != other['source_id'] for row in pg_repo.list_records())
        bad = document_record()
        bad['chunks'] = 0
        with pytest.raises(IntegrityError):
            pg_repo.insert(bad)
        assert all(row['source_id'] != bad['source_id'] for row in pg_repo.list_records())
    finally:
        pg_repo.delete(record['source_id'])


def test_backfill_is_idempotent_and_rolls_back_on_conflict(pg_repo):
    old = document_record()
    fresh = document_record()
    try:
        assert pg_repo.backfill([old]) == (1, 0)
        assert pg_repo.backfill([old]) == (0, 1)
        conflict = dict(old, filename='different.pdf')
        with pytest.raises(MetadataConflict):
            pg_repo.backfill([fresh, conflict])
        assert all(row['source_id'] != fresh['source_id'] for row in pg_repo.list_records())
        assert pg_repo.backfill([fresh]) == (1, 0)
    finally:
        pg_repo.delete(old['source_id'])
        pg_repo.delete(fresh['source_id'])


def test_corpus_upload_search_restart_and_delete_with_postgres(pg_repo, store):
    # Source PDFs and chunks are under pytest's temporary directory, never data/app.
    path = store.uploads_dir.parent
    def open_store():
        return CorpusStore(base_chunks_path=path / 'base.jsonl',
                           base_papers_dir=store.base_papers_dir,
                           uploads_dir=store.uploads_dir, metadata_repo=pg_repo)

    pg = open_store()
    original_count = pg.chunk_count
    snippet = 'Autonomous underwater robots map marine habitats using sonar and cameras.'
    payload = pdf_bytes(snippet)
    saved_id = None
    try:
        record, duplicate = pg.upload_pdf(payload, 'new-marine-robotics.pdf')
        saved_id = record['source_id']
        assert not duplicate
        assert any(r['source_id'] == saved_id for r in pg_repo.list_records())
        restarted = open_store()
        assert restarted.chunk_count > original_count
        assert restarted.search('underwater robots map marine habitats')[0]['source_id'] == saved_id
        assert restarted.pdf_path(saved_id)[0].read_bytes() == payload
        assert restarted.delete_upload(saved_id)
        assert open_store().chunk_count == original_count
        assert not any(r['source_id'] == saved_id for r in pg_repo.list_records())
    finally:
        if saved_id is not None:
            pg_repo.delete(saved_id)
