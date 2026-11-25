"""End-to-end smoke check for the Redis/RQ PDF ingestion API.

Usage: python scripts/smoke_ingestion_jobs.py path/to/paper.pdf
The PDF is uploaded to your RUNNING localhost Marine Evidence Finder.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    if not args.pdf.is_file():
        parser.error(f'PDF not found: {args.pdf}')
    base_url = args.base_url.rstrip('/')
    with args.pdf.open('rb') as handle:
        response = requests.post(base_url + '/ingestion-jobs',
                                 files={'file': (args.pdf.name, handle, 'application/pdf')}, timeout=45)
    response.raise_for_status()
    job = response.json()
    print(f"Queued: job_id={job['job_id']} status={job['status']}", flush=True)
    end = time.monotonic() + args.timeout
    while time.monotonic() < end:
        check = requests.get(base_url + job['status_url'], timeout=10)
        check.raise_for_status()
        current = check.json()
        print('Status:', current['status'], flush=True)
        if current['status'] == 'succeeded':
            docs = requests.get(base_url + '/documents', timeout=10)
            docs.raise_for_status()
            found = any(d['source_id'] == current['source_id'] for d in docs.json()['documents'])
            print(f"Document source_id={current['source_id']}, visible_in_API={found}")
            return 0 if found else 1
        if current['status'] == 'failed':
            print('Failure:', current.get('error') or 'unknown error', file=sys.stderr)
            return 1
        time.sleep(2)
    print('Timed out waiting for worker; inspect docker compose logs worker', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
