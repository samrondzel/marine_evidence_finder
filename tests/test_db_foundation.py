"""Database contract tests; uses SQLite, no Docker or live PostgreSQL needed."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marine_evidence.db_connection import database_url_from_env
from marine_evidence.db_models import Base, UploadedDocument


def make_document(sid='U1234567890ABCDEF', digest='a'*64):
    return UploadedDocument(
        source_id=sid, sha256=digest, filename='sample.pdf',
        title='Sample document', doi='', pages=2, chunks=5,
        added_at=datetime.now(timezone.utc),
    )


def test_metadata_insert_and_query():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    assert 'uploaded_documents' in inspect(engine).get_table_names()
    with Session(engine) as session:
        session.add(make_document())
        session.commit()
        found = session.scalar(select(UploadedDocument).where(UploadedDocument.sha256 == 'a'*64))
        assert found is not None
        assert (found.filename, found.chunks, found.pages) == ('sample.pdf', 5, 2)
    engine.dispose()


def test_sha256_prevents_duplicate_documents():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(make_document())
        session.commit()
        session.add(make_document(sid='U9999999999ABCDEF'))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    engine.dispose()


def test_invalid_chunk_count_is_rejected():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        doc = make_document()
        doc.chunks = 0
        session.add(doc)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    engine.dispose()


def test_database_url_safe_for_special_characters(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setenv('PGPASSWORD', 'my@password:/#')
    url = database_url_from_env()
    assert url.password == 'my@password:/#'
    assert url.host == 'db' and url.database == 'marine_evidence'


def test_database_url_requires_secret(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('PGPASSWORD', raising=False)
    with pytest.raises(RuntimeError, match='PGPASSWORD'):
        database_url_from_env()
