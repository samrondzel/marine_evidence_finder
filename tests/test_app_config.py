from pathlib import Path

from fastapi.testclient import TestClient

from marine_evidence.config import AppPaths
from marine_evidence.api import create_app
from test_corpus_store import store  # noqa: F401 -- fixture shared with existing API tests


def test_defaults_from_explicit_root(tmp_path):
    paths = AppPaths.from_environment(tmp_path, environ={})
    assert paths.project_root == tmp_path
    assert paths.base_chunks_path == tmp_path / 'data/chunks/word_safe/chunks.jsonl'
    assert paths.base_papers_dir == tmp_path / 'papers'
    assert paths.uploads_dir == tmp_path / 'data/app'
    assert paths.base_manifest_path == tmp_path / 'evaluation/papers_manifest.json'


def test_environment_root_and_relative_overrides(tmp_path):
    paths = AppPaths.from_environment(environ={
        'MARINE_PROJECT_ROOT': str(tmp_path),
        'MARINE_BASE_CHUNKS_PATH': 'my-data/docs.jsonl',
        'MARINE_UPLOADS_DIR': 'state/uploads',
    })
    assert paths.base_chunks_path == tmp_path / 'my-data/docs.jsonl'
    assert paths.uploads_dir == tmp_path / 'state/uploads'


def test_explicit_root_has_priority_over_environment(tmp_path):
    paths = AppPaths.from_environment(tmp_path, environ={'MARINE_PROJECT_ROOT': '/incorrect/root'})
    assert paths.project_root == tmp_path


def test_absolute_override(tmp_path):
    absolute = (tmp_path / 'uploads').resolve()
    paths = AppPaths.from_environment(environ={
        'MARINE_PROJECT_ROOT': str(tmp_path),
        'MARINE_UPLOADS_DIR': str(absolute),
    })
    assert paths.uploads_dir == absolute


def test_liveness_readiness_contracts(store):
    with TestClient(create_app(store=store)) as client:
        live = client.get('/health/live')
        ready = client.get('/health/ready')
        assert live.status_code == 200 and live.json() == {'status': 'alive'}
        assert ready.status_code == 200 and ready.json()['chunks'] == 1


def test_search_openapi_schema_and_response(store):
    with TestClient(create_app(store=store)) as client:
        schema = client.get('/openapi.json').json()
        ref = schema['paths']['/search']['post']['responses']['200']['content']['application/json']['schema']
        assert ref['$ref'].endswith('/SearchResponse')
        response = client.post('/search', json={'question': 'Whales communicate'})
        assert response.status_code == 200
        hit = response.json()['hits'][0]
        assert hit['source_id'] == 'P01' and hit['pdf_page'] == 1
        assert {'chunk_id','source_id','pdf_page','text','score'} <= set(hit)
