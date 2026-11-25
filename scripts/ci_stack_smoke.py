"""Additional live assertions for the disposable CI stack (no paid LLM calls)."""
from __future__ import annotations

import argparse
from pathlib import Path
import time
import requests

API = 'http://127.0.0.1:8000'
GRAFANA = 'http://127.0.0.1:3000'


def get_json(url: str):
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()


def search(question: str):
    r = requests.post(API + '/search', json={'question': question, 'top_k': 3}, timeout=10)
    r.raise_for_status()
    return r.json()['hits']


def check(root: Path):
    assert (root / 'ci.env').is_file(), 'Only run against the synthetic CI stack'
    assert any(x['source_id'] == 'CI01' for x in search('whale communication underwater'))
    docs = get_json(API + '/documents')['documents']
    uploaded = [d for d in docs if d.get('uploaded') and d['filename'] == 'ci-upload.pdf']
    assert len(uploaded) == 1, docs
    source = uploaded[0]['source_id']
    assert any(x['source_id'] == source for x in search('kelpbot sonar'))
    pdf = requests.get(API + f'/documents/{source}/pdf', timeout=10)
    pdf.raise_for_status()
    assert pdf.content == (root / 'ci-upload.pdf').read_bytes()
    r = requests.get('http://127.0.0.1:8501/_stcore/health', timeout=10)
    r.raise_for_status()
    # Provisioning and reconciler heartbeat may lag behind initial health checks.
    required_panels = {'LLM calls/sec by role', 'Observed tokens/sec (subsets shown separately)',
                       'Estimated USD since API start (priced calls only)',
                       'Unpriced calls since API start', 'Missing token fields since API start'}
    for attempt in range(20):
        try:
            ops = get_json(API + '/ops/status')
            assert ops['jobs']['succeeded'] == 1 and ops['jobs']['failed'] == 0, ops
            assert ops['reconciler_last_success_timestamp_seconds'] > time.time() - 60, ops
            dashboard = get_json(GRAFANA + '/api/dashboards/uid/marine-reliable-ai-s3')['dashboard']
            assert required_panels <= {p['title'] for p in dashboard['panels']}
            break
        except (AssertionError, requests.RequestException, KeyError, TypeError) as exc:
            if attempt == 19:
                raise RuntimeError('CI heartbeat/dashboard not ready') from exc
            time.sleep(3)
    print('PASS: synthetic PDF upload -> worker -> PostgreSQL -> API search/PDF, UI health, reconciler and Grafana cost panels')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    check(parser.parse_args().root)
