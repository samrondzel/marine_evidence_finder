"""Read-only Sprint 3 smoke test with startup grace for Prometheus/Grafana.

python scripts/smoke_observability.py
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

API = 'http://127.0.0.1:8000'
PROM = 'http://127.0.0.1:9090'
GRAFANA = 'http://127.0.0.1:3000'


def fetch(url: str):
    with urllib.request.urlopen(url, timeout=6) as resp:
        return resp.status, dict(resp.headers), resp.read().decode('utf-8')


def check_once():
    status, _, content = fetch(API + '/ops/status')
    snapshot = json.loads(content)
    assert status == 200 and snapshot['enabled'], snapshot

    status, headers, metrics = fetch(API + '/metrics')
    assert status == 200 and 'marine_http_requests_total' in metrics
    assert 'marine_ingestion_jobs' in metrics
    assert any(k.lower() == 'content-type' and 'text/plain' in v.lower()
               for k, v in headers.items()), headers

    status, _, targets_body = fetch(PROM + '/api/v1/targets?state=active')
    targets = json.loads(targets_body)
    assert status == 200 and targets['status'] == 'success'
    seen = [(target['labels'].get('job'), target.get('health'))
            for target in targets['data']['activeTargets']]
    assert ('marine-api', 'up') in seen, f'Prometheus target is not UP: {seen}'

    status, _, grafana_body = fetch(GRAFANA + '/api/health')
    assert status == 200
    return snapshot, json.loads(grafana_body)


def main():
    # Docker Compose starts processes but does not guarantee that Prometheus
    # has already performed its first five-second scrape or Grafana is ready.
    for attempt in range(30):
        try:
            snapshot, grafana = check_once()
        except (AssertionError, OSError, ValueError) as exc:
            if attempt == 29:
                raise RuntimeError(f'Observability smoke test failed: {exc}') from exc
            print(f'Waiting for observability services ({attempt+1}/30): {exc}')
            time.sleep(3)
            continue
        print('API /ops/status:', json.dumps(snapshot, indent=2))
        print('API /metrics: OK; http and ingestion metric families present')
        print('Prometheus scrape: UP')
        print('Grafana /api/health:', grafana.get('database', 'ok'))
        print('PASS: http://127.0.0.1:3000/d/marine-reliable-ai-s3')
        return


if __name__ == '__main__':
    main()
