import json
from pathlib import Path

import fitz
import pytest

from marine_evidence.corpus_store import CorpusStore, DocumentError, extract_uploaded_pdf


def pdf_bytes(text='Porpoises stopped feeding during ship noise. This sentence is observable data.'):
    d = fitz.open()
    p = d.new_page()
    p.insert_text((60, 60), text + "\n" + text + "\n" + text)
    value = d.tobytes()
    d.close()
    return value


@pytest.fixture()
def store(tmp_path):
    chunks = tmp_path / 'base.jsonl'
    chunks.write_text(json.dumps({
        'chunk_id': 'P01:p0001:c0001', 'source_id': 'P01', 'pdf_page': 1,
        'title': 'Old article', 'filename': 'old.pdf', 'doi': '', 'text': 'Whales communicate underwater.'
    }) + '\n', encoding='utf-8')
    papers = tmp_path / 'papers'
    papers.mkdir()
    (papers / 'old.pdf').write_bytes(pdf_bytes('Whales communicate underwater. This is the original paper.'))
    return CorpusStore(base_chunks_path=chunks, base_papers_dir=papers,
                       uploads_dir=tmp_path / 'uploads')


def test_upload_is_searchable_immediately_and_persists(store, tmp_path):
    data = pdf_bytes()
    doc, duplicate = store.upload_pdf(data, 'nested/path/Porpoise study.pdf')
    assert duplicate is False and doc['source_id'].startswith('U')
    assert doc['filename'] == 'Porpoise study.pdf'
    assert doc['pages'] == 1 and doc['chunks'] >= 1
    result = store.search('Porpoises stopped feeding', top_k=3)
    assert result[0]['source_id'] == doc['source_id']
    assert store.pdf_path(doc['source_id'])[0].read_bytes() == data
    second = CorpusStore(base_chunks_path=tmp_path / 'base.jsonl',
                         base_papers_dir=tmp_path / 'papers', uploads_dir=tmp_path / 'uploads')
    assert second.search('Porpoises stopped feeding')[0]['source_id'] == doc['source_id']
    assert len(second.list_documents()) == 2


def test_duplicate_upload_no_duplicate_chunks(store):
    blob = pdf_bytes()
    first, _ = store.upload_pdf(blob, 'new.pdf')
    count = store.chunk_count
    second, duplicate = store.upload_pdf(blob, 'another.pdf')
    assert duplicate is True and first == second and store.chunk_count == count


def test_uploaded_document_removable_original_protected(store):
    with pytest.raises(DocumentError, match='cannot be deleted'):
        store.delete_upload('P01')
    uploaded, _ = store.upload_pdf(pdf_bytes(), 'new.pdf')
    assert store.delete_upload(uploaded['source_id'])
    assert store.pdf_path(uploaded['source_id']) is None
    assert store.chunk_count == 1
    assert not store.delete_upload(uploaded['source_id'])


def test_invalid_pdf_rejected_no_disk_artifacts(store):
    count = store.chunk_count
    for blob, name in [(b'not a PDF', 'bad.pdf'), (pdf_bytes(), 'bad.txt')]:
        with pytest.raises(DocumentError):
            store.upload_pdf(blob, name)
    assert store.chunk_count == count
    assert not (store.uploads_dir / 'registry.json').exists()


def test_scanned_pdf_rejected(store):
    d = fitz.open()
    d.new_page()
    data = d.tobytes()
    d.close()
    with pytest.raises(DocumentError, match='too little selectable text'):
        store.upload_pdf(data, 'scan.pdf')


def test_page_provenance_and_immutable_base(store):
    data = pdf_bytes()
    document, _ = store.upload_pdf(data, 'paper.pdf')
    source = document['source_id']
    chunk = store.search('Porpoises')[0]
    assert chunk['chunk_id'].startswith(f'{source}:p0001:c')
    assert chunk['pdf_page'] == 1 and chunk['filename'] == 'paper.pdf'
    assert store.base_documents['P01']['chunks'] == 1
    assert store.pdf_path('../../etc/passwd') is None


def test_base_duplicate_by_checksum(tmp_path):
    data = pdf_bytes()
    manifest = tmp_path / 'manifest.json'
    import hashlib
    manifest.write_text(json.dumps([{'id': 'P01', 'pdf_page_count': 1,
                                     'sha256': hashlib.sha256(data).hexdigest()}]), encoding='utf-8')
    base_file = tmp_path / 'base.jsonl'
    base_file.write_text(json.dumps({'chunk_id': 'P01:p0001:c0001', 'source_id': 'P01',
        'pdf_page': 1, 'title': 'Base', 'filename': 'base.pdf', 'doi': '',
        'text': 'Porpoises stopped feeding.'})+'\n', encoding='utf-8')
    docs = tmp_path / 'papers'; docs.mkdir(); (docs/'base.pdf').write_bytes(data)
    s = CorpusStore(base_chunks_path=base_file, base_papers_dir=docs,
                    uploads_dir=tmp_path/'app', base_manifest_path=manifest)
    result, already = s.upload_pdf(data, 'base.pdf')
    assert already and result['source_id'] == 'P01' and s.chunk_count == 1
