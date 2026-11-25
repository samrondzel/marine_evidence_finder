"""Sprint 3: structured logs, privacy-safe labels, DB/Redis snapshots and heartbeat."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from marine_evidence.api import create_app
from marine_evidence.db_models import Base
from marine_evidence.ingestion_job_repository import IngestionJobRepository
from marine_evidence.observability import (
    JSONLogFormatter, RECONCILER_HEARTBEAT_KEY, new_request_id,
    publish_reconciler_heartbeat, request_id_context, state_snapshot,
)
from test_corpus_store import store  # noqa: F401


class FakeQueue:
    count = 3


class FakeRedis:
    def __init__(self):
        self.records = {}
        self.expiry = {}

    def set(self, key, value, ex=None):
        self.records[key] = value
        self.expiry[key] = ex

    def get(self, key):
        return self.records.get(key)


def make_repo(tmp_path):
    engine = create_engine('sqlite+pysqlite:///' + str(tmp_path / 'observability.sqlite'))
    Base.metadata.create_all(engine)
    return engine, IngestionJobRepository(engine)


def test_state_snapshot_is_aggregated_and_has_running_age(tmp_path):
    engine, repo = make_repo(tmp_path)
    repo.create('a'*32, 'secret-paper-name.pdf')
    repo.create('b'*32, 'other.pdf')
    assert repo.claim('a'*32)
    redis = FakeRedis()
    publish_reconciler_heartbeat(redis)
    summary = state_snapshot(repo, FakeQueue(), redis)
    assert summary['jobs']['queued'] == 1
    assert summary['jobs']['running'] == 1
    assert summary['jobs']['succeeded'] == 0
    assert summary['queue_depth'] == 3
    assert summary['oldest_running_seconds'] >= 0
    assert summary['reconciler_last_success_timestamp_seconds'] > 0
    assert redis.expiry[RECONCILER_HEARTBEAT_KEY] == 120
    assert 'secret-paper-name' not in str(summary)
    assert 'a'*32 not in str(summary)
    engine.dispose()


def test_metrics_and_ops_with_db_state_and_route_templates(tmp_path, store):
    engine, repo = make_repo(tmp_path)
    jid = 'a'*32
    repo.create(jid, 'private.pdf')
    app = create_app(store=store, jobs_repository=repo, job_queue=FakeQueue())
    with TestClient(app) as client:
        api_id = client.get('/health/live').headers['x-request-id']
        assert re.fullmatch('[0-9a-f]{32}', api_id)
        ops = client.get('/ops/status')
        assert ops.status_code == 200
        assert ops.json()['jobs']['queued'] == 1
        assert ops.json()['queue_depth'] == 3
        assert ops.json()['reconciler_last_success_timestamp_seconds'] is None
        assert client.get(f'/ingestion-jobs/{jid}').status_code == 200
        assert client.get('/ingestion-jobs/' + 'b'*32).status_code == 404
        assert client.get('/a-totally-unknown-' + 'c'*32).status_code == 404
        response = client.get('/metrics')
        assert response.status_code == 200
        assert 'text/plain' in response.headers['content-type']
        body = response.text
        assert 'marine_http_requests_total' in body
        assert 'route="/ingestion-jobs/{job_id}"' in body
        assert 'route="_unmatched"' in body
        assert 'marine_ingestion_jobs{status="queued"} 1.0' in body
        assert 'marine_rq_queue_depth 3.0' in body
        assert jid not in body
        assert 'private.pdf' not in body
        assert 'a-totally-unknown-' not in body
        # Scrapes must not increment HTTP request metrics themselves.
        assert 'route="/metrics"' not in body
    engine.dispose()


def test_logging_format_only_emits_safe_fields():
    token = request_id_context.set(new_request_id())
    try:
        record = logging.LogRecord('marine_evidence.api', logging.INFO, 'api.py', 42,
                                   'http_request_complete', (), None)
        record.event = 'http_request_complete'
        record.http_route = '/ingestion-jobs/{job_id}'
        record.status_code = 200
        record.question = 'A private research question'
        record.api_key = 'sk-NEVER-LOG'
        output = json.loads(JSONLogFormatter('api').format(record))
        assert output['service'] == 'api'
        assert output['event'] == 'http_request_complete'
        assert output['http_route'] == '/ingestion-jobs/{job_id}'
        assert output['status_code'] == 200
        assert re.fullmatch('[0-9a-f]{32}', output['request_id'])
        assert 'private' not in str(output).lower()
        assert 'NEVER-LOG' not in str(output)
    finally:
        request_id_context.reset(token)


def test_snapshot_when_background_ingestion_disabled():
    assert state_snapshot() == {'enabled': False, 'jobs': {}, 'queue_depth': None,
        'oldest_running_seconds': None, 'reconciler_last_success_timestamp_seconds': None}


def test_prometheus_dashboard_json_is_loadable():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    dashboard = json.loads((root/'observability/grafana/dashboards/marine_reliable_ai.json').read_text())
    assert len(dashboard['panels']) >= 8
    assert any('marine_http_requests_total' in p['targets'][0]['expr'] for p in dashboard['panels'])
