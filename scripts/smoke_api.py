"""Read-only smoke test for a running Marine Evidence Finder API.

Example: python scripts/smoke_api.py --base-url http://127.0.0.1:8000
This does NOT upload/delete files or call the paid /ask endpoint.
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def get_json(base: str, path: str, *, payload: dict | None = None) -> dict:
    url = base.rstrip('/') + path
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    headers = {'Accept': 'application/json'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    request = Request(url, data=data, headers=headers)
    with urlopen(request, timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(f'{path}: unexpected HTTP {resp.status}')
        content = json.load(resp)
    if not isinstance(content, dict):
        raise RuntimeError(f'{path}: expected JSON object')
    return content


def smoke(base: str) -> None:
    # Newer deployments may offer a dependency-aware readiness endpoint.
    # The older archive only exposes /health; prefer /health/ready when present.
    try:
        health = get_json(base, '/health/ready')
        health_path = '/health/ready'
    except HTTPError as exc:
        if exc.code != 404:
            raise
        health = get_json(base, '/health')
        health_path = '/health'
    if health.get('status') not in ('ok', 'ready', 'healthy'):
        raise RuntimeError(f'{health_path}: unhealthy response {health!r}')
    print(f'PASS {health_path}: {health}')

    doc = get_json(base, '/documents')
    if not isinstance(doc.get('documents'), list):
        raise RuntimeError('/documents: expected a documents list')
    print(f'PASS /documents: {len(doc["documents"])} documents')

    query = {'question': 'What do researchers report about whale communication?', 'top_k': 3}
    results = get_json(base, '/search', payload=query)
    if not isinstance(results.get('hits'), list):
        raise RuntimeError('/search: expected a hits list')
    print(f'PASS /search: {len(results["hits"])} hits')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    try:
        smoke(args.base_url)
    except (HTTPError, URLError, RuntimeError, ValueError, TimeoutError) as exc:
        print(f'FAIL smoke test: {exc}', file=sys.stderr)
        return 1
    print('SMOKE PASSED: API responded correctly; no data was changed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
