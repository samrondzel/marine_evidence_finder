"""Contracts for the local Compose deployment (no Docker daemon needed)."""
from pathlib import Path

from marine_evidence.ui_urls import pdf_link

ROOT = Path(__file__).resolve().parents[1]


def test_public_pdf_links_use_browser_address_not_internal_docker_dns(monkeypatch):
    monkeypatch.setenv('MARINE_API_URL', 'http://api:8000')
    monkeypatch.setenv('MARINE_PUBLIC_API_URL', 'http://127.0.0.1:8000/')
    assert pdf_link('P01', 12) == 'http://127.0.0.1:8000/documents/P01/pdf#page=12'
    assert 'api:8000' not in pdf_link('P01', 12)


def test_public_links_encode_untrusted_ids():
    assert pdf_link('abc/def ?') == 'http://127.0.0.1:8000/documents/abc%2Fdef%20%3F/pdf#page=1'


def test_compose_local_port_and_volume_safety():
    compose = (ROOT / 'compose.yaml').read_text(encoding='utf-8')
    assert '127.0.0.1:8000:8000' in compose
    assert '127.0.0.1:8501:8501' in compose
    assert '--workers", "1' in compose
    assert 'source: ./data/app' in compose
    assert 'source: ./data/chunks/word_safe' in compose
    assert 'read_only: true' in compose
    assert 'condition: service_healthy' in compose


def test_secrets_not_copied_into_image():
    ignored = (ROOT / '.dockerignore').read_text(encoding='utf-8').splitlines()
    assert '.env' in ignored
    assert 'papers/' in ignored
    assert 'data/' in ignored
    dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
    assert 'COPY . .' not in dockerfile
    assert 'USER marine' in dockerfile


def test_streamlit_uses_separate_internal_and_public_urls():
    streamlit = (ROOT / 'streamlit_app.py').read_text(encoding='utf-8')
    assert "os.environ.get('MARINE_API_URL'" in streamlit
    assert 'from marine_evidence.ui_urls import pdf_link' in streamlit
