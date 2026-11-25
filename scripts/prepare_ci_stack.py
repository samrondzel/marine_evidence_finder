"""Create a fresh, synthetic Compose workspace; never modify a real corpus."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

import fitz

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    'pyproject.toml', 'requirements-answer.txt', 'requirements-app.txt',
    'requirements-db.txt', 'requirements-jobs.txt', 'Dockerfile', 'Dockerfile.jobs',
    'Dockerfile.metadata', 'Dockerfile.migrations', 'Dockerfile.migrations.dockerignore',
    '.dockerignore', 'alembic.ini', 'streamlit_app.py', 'compose.yaml',
    'compose.postgres.yaml', 'compose.metadata.yaml', 'compose.jobs.yaml',
    'compose.observability.yaml', 'config/llm_prices.json',
)
BASE_TEXT = 'Synthetic CI fixture: whale communication and underwater vessel noise. This is not scientific evidence.'
UPLOAD_TEXT = 'Synthetic CI fixture: a robot named kelpbot maps habitats using sonar. This is not scientific evidence.'


def make_pdf(path: Path, sentence: str) -> None:
    with fitz.open() as doc:
        page = doc.new_page()
        for y in (60, 85, 110):
            page.insert_text((45, y), sentence, fontsize=9)
        doc.save(path)


def prepare(destination: Path, source: Path = ROOT) -> None:
    # exist_ok=False is intentional, even for an empty destination.
    destination.mkdir(parents=True, exist_ok=False)
    for rel in FILES:
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / rel, target)
    for rel in ('src/marine_evidence', 'migrations', 'observability'):
        shutil.copytree(source / rel, destination / rel,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    papers = destination / 'papers'; papers.mkdir()
    chunks = destination / 'data/chunks/word_safe'; chunks.mkdir(parents=True)
    uploads = destination / 'data/app'; uploads.mkdir(parents=True)
    # Containers run as uid 10001. World-writable ONLY in the disposable CI fixture.
    uploads.chmod(0o777)
    evaluation = destination / 'evaluation'; evaluation.mkdir()
    pdf = papers / 'ci-base.pdf'
    make_pdf(pdf, BASE_TEXT)
    with fitz.open(pdf) as doc:
        text = doc[0].get_text().strip()
    row = {'chunk_id': 'CI01:p0001:c0001', 'source_id': 'CI01', 'pdf_page': 1,
           'title': 'Synthetic CI base', 'filename': pdf.name, 'doi': '', 'text': text}
    (chunks / 'chunks.jsonl').write_text(json.dumps(row) + '\n', encoding='utf-8')
    (evaluation / 'papers_manifest.json').write_text(json.dumps([{
        'id': 'CI01', 'local_pdf_filename': pdf.name, 'title': row['title'], 'doi': '',
        'pdf_page_count': 1, 'sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(),
    }]), encoding='utf-8')
    # Not mounted in containers: uploaded via the actual HTTP endpoint.
    make_pdf(destination / 'ci-upload.pdf', UPLOAD_TEXT)
    (destination / 'ci.env').write_text('OPENAI_API_KEY=\nMARINE_DB_PASSWORD=local_ci_only\n', encoding='utf-8')
    print(f'Created synthetic CI workspace: {destination}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    prepare(parser.parse_args().destination)
