"""Local observability: structured application logs and bounded Prometheus metrics.

The API is single-process in Docker Compose. Metrics are intentionally kept in
its own registry; worker/reconciler status is derived from durable PostgreSQL
and Redis, not from process-local counters in the worker.
"""
from __future__ import annotations

import json
import logging
import os
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from .llm_usage import TOKEN_FIELDS, ROLES, RESPONSE_STATUSES

RECONCILER_HEARTBEAT_KEY = 'marine:observability:reconciler_last_success'
request_id_context: ContextVar[str | None] = ContextVar('marine_request_id', default=None)
SAFE_EXTRA_FIELDS = (
    'event', 'job_id', 'rq_job_id', 'source_id', 'http_method', 'http_route',
    'status_code', 'duration_ms', 'attempts', 'planned_retries', 'enqueued',
    'failed', 'errors', 'examined', 'retry_at', 'tool', 'result_count',
    'agent_status', 'steps', 'tool_calls', 'llm_mode', 'llm_calls', 'unpriced_calls',
    'input_tokens', 'output_tokens', 'reasoning_tokens', 'cached_input_tokens',
    'estimated_cost_usd', 'known_cost_usd', 'total_tokens',
)
JOB_STATUSES = ('queued', 'running', 'succeeded', 'failed')


class JSONLogFormatter(logging.Formatter):
    """Serialize only allowlisted structured fields; never log request bodies."""

    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        out = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec='milliseconds'),
            'level': record.levelname,
            'service': self.service,
            'logger': record.name,
            'message': record.getMessage(),
        }
        request_id = request_id_context.get()
        if request_id:
            out['request_id'] = request_id
        for field in SAFE_EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None and isinstance(value, (str, int, float, bool)):
                out[field] = value
        if record.exc_info:
            out['exception'] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, separators=(',', ':'))


def configure_logging(service: str) -> None:
    """Opt-in JSON for our services; unchanged standard logging in local tests."""
    if os.getenv('MARINE_LOG_FORMAT', 'text').lower() != 'json':
        logging.basicConfig(level=logging.INFO)
        return
    root = logging.getLogger()
    # Reconfigure only inside processes explicitly opting in via Compose.
    handler = logging.StreamHandler()
    handler.setFormatter(JSONLogFormatter(service=service))
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


def new_request_id() -> str:
    # Never accept user-provided request IDs as a metric label/log injection.
    return uuid4().hex


def _to_utc(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def state_snapshot(repository=None, queue=None, redis_client=None) -> dict:
    """One cheap aggregate DB read + queue depth + reconciler heartbeat.

    No filenames, PDF contents, questions, job IDs or RQ registry scans.
    Exceptions propagate so monitoring does not report false zero values.
    """
    if repository is None:
        return {'enabled': False, 'jobs': {}, 'queue_depth': None,
                'oldest_running_seconds': None, 'reconciler_last_success_timestamp_seconds': None}

    summary = repository.observability_snapshot()
    jobs = {status: int(summary['counts'].get(status, 0)) for status in JOB_STATUSES}
    start = _to_utc(summary['oldest_running'])
    age = max(0.0, (datetime.now(timezone.utc) - start).total_seconds()) if start else 0.0
    queue_depth = int(queue.count) if queue is not None else None
    heartbeat = None
    if redis_client is not None:
        raw = redis_client.get(RECONCILER_HEARTBEAT_KEY)
        heartbeat = float(raw) if raw is not None else None
    return {
        'enabled': True,
        'jobs': jobs,
        'queue_depth': queue_depth,
        'oldest_running_seconds': round(age, 3),
        'reconciler_last_success_timestamp_seconds': heartbeat,
    }


class ApiMetrics:
    def __init__(self):
        self.registry = CollectorRegistry()
        self.requests = Counter('marine_http_requests_total', 'Completed HTTP requests',
                                ['method', 'route', 'status'], registry=self.registry)
        self.latency = Histogram('marine_http_request_duration_seconds', 'HTTP request duration',
                                 ['method', 'route'], registry=self.registry,
                                 buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
        self.agent_runs = Counter('marine_agent_runs_total', 'Completed agent research runs',
                                  ['outcome', 'stop_reason'], registry=self.registry)
        self.agent_tool_calls = Counter('marine_agent_tool_calls_total', 'Agent read-only tool executions',
                                        ['tool'], registry=self.registry)
        self.agent_duration = Histogram('marine_agent_run_duration_seconds', 'Full agent run time',
                                        registry=self.registry,
                                        buckets=(0.25, 1, 2.5, 5, 10, 30, 60, 120, 240))
        self.llm_calls = Counter('marine_llm_calls_total', 'Logical SDK calls including failures',
                                 ['mode', 'role', 'response_status'], registry=self.registry)
        self.llm_tokens = Counter('marine_llm_tokens_total', 'Observed provider token counts; cached and reasoning are subsets',
                                  ['mode', 'role', 'kind'], registry=self.registry)
        self.llm_missing = Counter('marine_llm_missing_token_fields_total', 'Calls missing a usable token field',
                                   ['mode', 'role', 'kind'], registry=self.registry)
        self.llm_cost = Counter('marine_llm_estimated_cost_usd_total', 'Estimated cost of priced standard text calls only',
                                ['mode', 'role'], registry=self.registry)
        self.llm_unpriced = Counter('marine_llm_unpriced_calls_total', 'Logical SDK calls without an estimate',
                                    ['mode', 'role'], registry=self.registry)
        self.in_flight = Gauge('marine_http_in_flight_requests', 'Active requests',
                               registry=self.registry)
        self.job_count = Gauge('marine_ingestion_jobs', 'Persistent ingestion jobs by status',
                               ['status'], registry=self.registry)
        self.queue_depth = Gauge('marine_rq_queue_depth', 'Jobs waiting in marine-ingest Redis queue',
                                 registry=self.registry)
        self.oldest_running = Gauge('marine_oldest_running_job_age_seconds',
                                    'Age of oldest running ingestion job', registry=self.registry)
        self.reconciler_success = Gauge('marine_reconciler_last_success_timestamp_seconds',
                                       'Last successful Reconciler pass (Unix seconds; zero if unknown)',
                                       registry=self.registry)
        # Seed known low-cardinality series so the first observed event has a
        # zero baseline if Prometheus has scraped before that event.
        for mode, role in (('baseline', 'generator'), ('agent', 'planner'), ('agent', 'generator')):
            for status in RESPONSE_STATUSES:
                self.llm_calls.labels(mode=mode, role=role, response_status=status)
            for kind in TOKEN_FIELDS:
                self.llm_tokens.labels(mode=mode, role=role, kind=kind)
                self.llm_missing.labels(mode=mode, role=role, kind=kind)
            self.llm_cost.labels(mode=mode, role=role)
            self.llm_unpriced.labels(mode=mode, role=role)
        for status in JOB_STATUSES:
            self.job_count.labels(status=status).set(0)

    def observe(self, method: str, route: str, status: int, elapsed_seconds: float) -> None:
        # Route MUST be a template from FastAPI or a constant sentinel.
        self.requests.labels(method=method, route=route, status=str(status)).inc()
        self.latency.labels(method=method, route=route).observe(elapsed_seconds)

    def observe_agent(self, result: dict) -> None:
        # Labels come only from fixed internal enums, never user text or chunk IDs.
        self.agent_runs.labels(outcome=result['status'], stop_reason=result['stop_reason']).inc()
        self.agent_duration.observe(result['elapsed_ms'] / 1000.0)
        for item in result['trace']:
            if item['action'] in ('search_bm25', 'expand_context') and 'outcome' not in item:
                self.agent_tool_calls.labels(tool=item['action']).inc()

    def observe_llm(self, mode: str, usage: dict) -> None:
        if mode not in ('baseline', 'agent'):
            raise ValueError('Unknown LLM metrics mode')
        for call in usage['calls']:
            role = call['role']
            if role not in ROLES:
                raise ValueError('Unknown LLM role')
            self.llm_calls.labels(mode=mode, role=role, response_status=call['response_status']).inc()
            for field in TOKEN_FIELDS:
                count = call[field]
                if count is None:
                    self.llm_missing.labels(mode=mode, role=role, kind=field).inc()
                else:
                    self.llm_tokens.labels(mode=mode, role=role, kind=field).inc(count)
            if call['estimated_cost_usd'] is None:
                self.llm_unpriced.labels(mode=mode, role=role).inc()
            else:
                self.llm_cost.labels(mode=mode, role=role).inc(call['estimated_cost_usd'])
        logging.getLogger(__name__).info('llm_usage_summary', extra={
            'event': 'llm_usage_summary', 'llm_mode': mode,
            **{k: v for k, v in usage.items() if k != 'calls'},
        })

    def set_snapshot(self, snapshot: dict) -> None:
        for status in JOB_STATUSES:
            self.job_count.labels(status=status).set(snapshot['jobs'].get(status, 0))
        # No async ingestion: use -1 to mean unavailable, not falsely healthy.
        self.queue_depth.set(snapshot['queue_depth'] if snapshot['queue_depth'] is not None else -1)
        self.oldest_running.set(snapshot['oldest_running_seconds'] if snapshot['oldest_running_seconds'] is not None else -1)
        self.reconciler_success.set(snapshot['reconciler_last_success_timestamp_seconds'] or 0)


def publish_reconciler_heartbeat(redis_conn) -> None:
    """TTL guards against stale 'healthy' readings after a daemon dies."""
    redis_conn.set(RECONCILER_HEARTBEAT_KEY, str(time.time()), ex=120)
