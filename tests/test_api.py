from types import SimpleNamespace

from fastapi.testclient import TestClient

from marine_evidence.api import create_app
from test_corpus_store import pdf_bytes, store  # noqa: F401  -- fixture comes from module


def test_health_upload_search_pdf_and_delete(store):
    app = create_app(store=store)
    with TestClient(app) as client:
        health = client.get('/health')
        assert health.status_code == 200 and health.json()['documents'] == 1
        out = client.post('/documents', files={'file': ('sample.pdf', pdf_bytes(), 'application/pdf')})
        assert out.status_code == 201, out.text
        sid = out.json()['document']['source_id']
        assert client.get('/health').json()['documents'] == 2
        hits = client.post('/search', json={'question': 'Porpoises stopped feeding', 'top_k': 5})
        assert hits.status_code == 200
        assert hits.json()['hits'][0]['source_id'] == sid
        pdf = client.get(f'/documents/{sid}/pdf')
        assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF-')
        assert 'inline' in pdf.headers['content-disposition']
        assert client.get('/documents/P01/pdf').status_code == 200
        assert client.get('/documents/not-real/pdf').status_code == 404
        assert client.delete('/documents/P01').status_code == 403
        assert client.delete(f'/documents/{sid}').status_code == 200
        assert client.post('/search', json={'question': 'Porpoises stopped feeding'}).json()['hits'] == []


def test_input_limits_and_bad_upload(store):
    with TestClient(create_app(store=store)) as client:
        assert client.post('/search', json={'question': '', 'top_k': 5}).status_code == 422
        assert client.post('/search', json={'question': 'good', 'top_k': 30}).status_code == 422
        assert client.post('/documents', files={'file': ('bad.txt', b'X', 'text/plain')}).status_code == 422
        assert client.post('/documents', files={'file': ('bad.pdf', b'X', 'application/pdf')}).status_code == 422


def test_ask_mock_generator_without_real_api(store, monkeypatch):
    from marine_evidence import api as api_module
    def fake_answer(question, index, model, top_k, distinct_pages):
        hits = index.search(question, top_k=top_k)
        return {'question': question, 'status': 'answered', 'claims': [
            {'statement': 'Whales communicate underwater.', 'citation_ids': [hits[0]['chunk_id']]}],
            'reason': '', 'citations': [{'chunk_id': hits[0]['chunk_id'],
              'source_id': hits[0]['source_id'], 'pdf_page': hits[0]['pdf_page']}],
            'retrieved': [], 'model': model}
    monkeypatch.setattr(api_module, 'answer_question', fake_answer)
    with TestClient(create_app(store=store)) as client:
        result = client.post('/ask', json={'question': 'Whales communicate', 'top_k': 5})
    assert result.status_code == 200
    assert result.json()['citations'][0]['source_id'] == 'P01'
