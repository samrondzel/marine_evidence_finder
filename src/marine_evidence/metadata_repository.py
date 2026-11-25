"""SQLAlchemy metadata repository. PostgreSQL owns uploaded-document metadata.

No CREATE TABLE on application startup; Alembic creates and upgrades schema.
Use one API worker: a database alone does not synchronize process-local BM25.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .db_models import UploadedDocument

FIELDS = ('source_id', 'sha256', 'filename', 'title', 'doi', 'pages', 'chunks')


def _as_model(record: dict[str, Any]) -> UploadedDocument:
    return UploadedDocument(
        **{name: record[name] for name in FIELDS},
        added_at=datetime.fromisoformat(record['added_at']),
    )


def _as_record(row: UploadedDocument) -> dict[str, Any]:
    return {
        **{name: getattr(row, name) for name in FIELDS},
        'added_at': row.added_at.isoformat(timespec='seconds'),
        'uploaded': True,
    }


class MetadataConflict(RuntimeError):
    """An existing record disagrees with a legacy JSON registry entry."""


class UploadedDocumentRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def ping(self) -> None:
        with self.engine.connect() as conn:
            conn.execute(text('SELECT 1'))

    def list_records(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.scalars(select(UploadedDocument).order_by(UploadedDocument.source_id)).all()
            return [_as_record(row) for row in rows]

    def insert(self, record: dict[str, Any]) -> None:
        # DB uniqueness constraints defend against concurrent INSERTs.
        with Session(self.engine) as session, session.begin():
            session.add(_as_model(record))

    def delete(self, source_id: str) -> bool:
        with Session(self.engine) as session, session.begin():
            row = session.get(UploadedDocument, source_id)
            if row is None:
                return False
            session.delete(row)
            return True

    def backfill(self, records: Iterable[dict[str, Any]]) -> tuple[int, int]:
        """Insert missing legacy uploads in one transaction; repeat runs do not duplicate.

        Intended only for the ONE-TIME legacy migration. Running this command
        again after a PostgreSQL-based deletion can resurrect old JSON records.
        """
        inserted = skipped = 0
        seen: set[str] = set()
        with Session(self.engine) as session, session.begin():
            for record in records:
                sid = record['source_id']
                if sid in seen:
                    raise MetadataConflict(f'Duplicate legacy source ID: {sid}')
                seen.add(sid)
                existing = session.get(UploadedDocument, sid)
                if existing is None:
                    other = session.scalar(select(UploadedDocument).where(UploadedDocument.sha256 == record['sha256']))
                    if other is not None:
                        raise MetadataConflict(f'SHA-256 already belongs to another source: {sid}')
                    session.add(_as_model(record))
                    inserted += 1
                    session.flush()  # Surface uniqueness errors before the next record.
                elif any(getattr(existing, key) != record[key] for key in FIELDS):
                    raise MetadataConflict(f'Conflicting metadata already in database: {sid}')
                else:
                    skipped += 1
        return inserted, skipped
