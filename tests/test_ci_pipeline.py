from pathlib import Path

import pytest

from marine_evidence.corpus_store import CorpusStore, extract_uploaded_pdf
from scripts.check_ci_inputs import forbidden_path
from scripts.prepare_ci_stack import prepare


@pytest.mark.parametrize('path', ['.env', 'nested/.env.prod', 'papers/a.pdf',
                                  'data/app/registry.json', 'archive.ZIP', 'secrets/tls.key'])
def test_forbidden_tracked_paths(path):
    assert forbidden_path(path)


@pytest.mark.parametrize('path', ['.env.example', 'src/marine_evidence/api.py',
                                  'evaluation/benchmark_agent_holdout_candidate.jsonl'])
def test_allowed_tracked_paths(path):
    assert not forbidden_path(path)


def test_ci_workspace_is_synthetic_and_non_overwriting(tmp_path):
    root = tmp_path / 'stack'
    prepare(root)
    assert not (root / '.env').exists()
    assert list((root / 'papers').iterdir()) == [root / 'papers/ci-base.pdf']
    assert not list((root / 'data/app').iterdir())
    store = CorpusStore.from_project(root)
    assert store.chunk_count == 1
    assert store.search('whale communication')[0]['source_id'] == 'CI01'
    assert store.pdf_path('CI01')[0].read_bytes().startswith(b'%PDF')
    record, chunks = extract_uploaded_pdf((root / 'ci-upload.pdf').read_bytes(), 'ci-upload.pdf')
    assert record['source_id'].startswith('U')
    assert 'kelpbot' in chunks[0]['text']
    with pytest.raises(FileExistsError):
        prepare(root)
