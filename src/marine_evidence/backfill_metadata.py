"""ONE-TIME, verified migration from legacy registry.json to PostgreSQL.

Dry run is default. Never deletes registry.json or stored PDF/chunk files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .bm25 import read_chunks
from .config import AppPaths
from .db_connection import make_engine
from .metadata_repository import UploadedDocumentRepository

SOURCE_ID = re.compile(r'^U[A-Z0-9_-]{1,40}$')
SHA256 = re.compile(r'^[a-f0-9]{64}$')


def verified_legacy_records(uploads_dir: Path) -> list[dict[str, Any]]:
    """Fail closed if ANY registry entry is missing, corrupt, or inconsistent."""
    registry_path = Path(uploads_dir) / 'registry.json'
    if not registry_path.is_file():
        raise ValueError(f'Legacy registry missing: {registry_path} (do not create an empty one)')
    records = json.loads(registry_path.read_text(encoding='utf-8'))
    if not isinstance(records, list):
        raise ValueError('Legacy registry must be a JSON list')
    seen_ids, seen_hashes = set(), set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError('Invalid legacy registry row')
        sid = record.get('source_id')
        sha = record.get('sha256')
        if not isinstance(sid, str) or not SOURCE_ID.fullmatch(sid) or sid in seen_ids:
            raise ValueError(f'Invalid or duplicate source ID: {sid!r}')
        if not isinstance(sha, str) or not SHA256.fullmatch(sha) or sha in seen_hashes:
            raise ValueError(f'Invalid or duplicate SHA256: {sid}')
        if not isinstance(record.get('filename'), str) or len(record['filename']) > 180:
            raise ValueError(f'Invalid filename: {sid}')
        if not isinstance(record.get('title'), str) or len(record['title']) > 200:
            raise ValueError(f'Invalid title: {sid}')
        if not isinstance(record.get('doi', ''), str) or len(record.get('doi', '')) > 255:
            raise ValueError(f'Invalid DOI: {sid}')
        if not isinstance(record.get('pages'), int) or record['pages'] <= 0:
            raise ValueError(f'Invalid pages: {sid}')
        if not isinstance(record.get('chunks'), int) or record['chunks'] <= 0:
            raise ValueError(f'Invalid chunks: {sid}')
        if record.get('uploaded') is not True:
            raise ValueError(f'Not an uploaded document: {sid}')
        if not isinstance(record.get('added_at'), str):
            raise ValueError(f'Missing added_at: {sid}')
        pdf = Path(uploads_dir) / 'pdfs' / f'{sid}.pdf'
        chunks = Path(uploads_dir) / 'chunks' / f'{sid}.jsonl'
        if not pdf.is_file() or not chunks.is_file():
            raise ValueError(f'Missing PDF/chunks: {sid}')
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != sha:
            raise ValueError(f'PDF SHA-256 mismatch: {sid}')
        rows = read_chunks(chunks)
        if len(rows) != record['chunks'] or any(r.get('source_id') != sid for r in rows):
            raise ValueError(f'Chunk count / provenance mismatch: {sid}')
        seen_ids.add(sid)
        seen_hashes.add(sha)
    return records


def plan_backfill(repo: UploadedDocumentRepository, records: list[dict[str, Any]]) -> tuple[int, int]:
    """Check all metadata matches before offering --apply."""
    from .metadata_repository import FIELDS, MetadataConflict
    existing = {r['source_id']: r for r in repo.list_records()}
    by_sha = {r['sha256']: r['source_id'] for r in existing.values()}
    to_insert = skipped = 0
    for r in records:
        other = existing.get(r['source_id'])
        if other:
            if any(other[key] != r[key] for key in FIELDS):
                raise MetadataConflict(f'Conflicting metadata: {r["source_id"]}')
            skipped += 1
        else:
            if r['sha256'] in by_sha:
                raise MetadataConflict(f'SHA-256 already used: {r["source_id"]}')
            to_insert += 1
    return to_insert, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Migrate existing uploads from registry.json to PostgreSQL')
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument('--dry-run', action='store_true', help='Check only (default)')
    choice.add_argument('--apply', action='store_true', help='Insert missing metadata into PostgreSQL')
    args = parser.parse_args(argv)
    paths = AppPaths.from_environment()
    records = verified_legacy_records(paths.uploads_dir)
    engine = make_engine()
    try:
        repo = UploadedDocumentRepository(engine)
        missing, already = plan_backfill(repo, records)
        print(f'Legacy uploads verified: {len(records)}; to insert: {missing}; already in DB: {already}')
        if args.apply:
            inserted, skipped = repo.backfill(records)
            print(f'Backfill committed: inserted={inserted}; existing={skipped}')
        else:
            print('Dry run only. No database changes. Pass --apply to insert.')
    finally:
        engine.dispose()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
