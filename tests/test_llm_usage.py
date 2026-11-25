"""Sprint 4.3: provider usage, cost accounting and API request isolation; no network."""
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from marine_evidence import agent, answer, api
from marine_evidence.llm_usage import load_prices, usage_scope, tracked_create
from marine_evidence.observability import ApiMetrics
from test_corpus_store import store  # noqa: F401
from test_agent import decision

MODEL = 'gpt-5-mini-2025-08-07'
PRICES = {MODEL: {'input': Decimal('0.25'), 'cached_input': Decimal('0.025'), 'output': Decimal('2')}}


def response(payload=None, *, model=MODEL, status='completed', tier='default', usage=True):
    return NS(model=model, status=status, service_tier=tier,
              usage=NS(input_tokens=1000, input_tokens_details=NS(cached_tokens=200),
                       output_tokens=500, output_tokens_details=NS(reasoning_tokens=300)) if usage else None,
              output_text=json.dumps(payload or {}), incomplete_details=NS(reason='max_output_tokens'))


def fake_client(result):
    return NS(responses=NS(create=lambda **kw: result))


def test_cost_uses_cached_discount_and_does_not_double_count_reasoning():
    with usage_scope(PRICES) as ledger:
        tracked_create(fake_client(response()), 'planner', model='gpt-5-mini')
        tracked_create(fake_client(response()), 'generator', model='gpt-5-mini')
        out = ledger.summary()
    assert out['llm_calls'] == 2 and out['unpriced_calls'] == 0
    assert out['input_tokens'] == 2000 and out['cached_input_tokens'] == 400
    assert out['output_tokens'] == 1000 and out['reasoning_tokens'] == 600
    assert out['total_tokens'] == 3000
    assert out['estimated_cost_usd'] == pytest.approx(0.00241)
    assert out['calls'][0]['model'] == MODEL
    assert out['calls'][0]['pricing_usd_per_million']['cached_input'] == 0.025


@pytest.mark.parametrize('model,tier,usage', [('unlisted', 'default', True), (MODEL, 'priority', True), (MODEL, 'default', False)])
def test_unknown_price_or_usage_is_not_zero(model, tier, usage):
    with usage_scope(PRICES) as ledger:
        tracked_create(fake_client(response(model=model, tier=tier, usage=usage)), 'generator', model='gpt-5-mini')
        out = ledger.summary()
    assert out['estimated_cost_usd'] is None and out['unpriced_calls'] == 1
    assert out['input_tokens'] == (1000 if usage else None)


def test_missing_detail_does_not_invent_cache_or_reasoning_counts():
    obj = response()
    obj.usage.input_tokens_details = None
    obj.usage.output_tokens_details = None
    with usage_scope(PRICES) as ledger:
        tracked_create(fake_client(obj), 'generator', model=MODEL)
        out = ledger.summary()
    assert out['cached_input_tokens'] is None and out['reasoning_tokens'] is None
    assert out['total_tokens'] == 1500 and out['estimated_cost_usd'] is None


def test_transport_error_and_incomplete_response_accounted_before_validation():
    def fail(**kw):
        raise TimeoutError('secret error string')
    with usage_scope(PRICES) as ledger:
        with pytest.raises(answer.AnswerError):
            answer.call_openai('secret question', [], model=MODEL, client=NS(responses=NS(create=fail)))
        with pytest.raises(answer.AnswerError, match='incomplete'):
            agent.call_agent_planner('secret question', {}, model=MODEL,
                                     client=fake_client(response(status='incomplete')))
        out = ledger.summary()
    assert out['llm_calls'] == 2 and out['unpriced_calls'] == 1
    assert out['estimated_cost_usd'] is None and out['known_cost_usd'] == pytest.approx(0.001205)
    assert out['calls'][0]['response_status'] == 'request_error'
    assert out['calls'][1]['response_status'] == 'incomplete'
    assert 'secret' not in str(out)
    metrics = ApiMetrics()
    metrics.observe_llm('agent', out)
    body = generate_latest(metrics.registry).decode()
    assert 'marine_llm_calls_total{mode="agent",response_status="incomplete",role="planner"} 1.0' in body
    assert 'marine_llm_unpriced_calls_total{mode="agent",role="generator"} 1.0' in body
    assert 'marine_llm_tokens_total{kind="reasoning_tokens",mode="agent",role="planner"} 300.0' in body
    assert MODEL not in body and 'secret' not in body


def test_concurrent_ledgers_and_scope_reset():
    from threading import Barrier
    barrier = Barrier(2)
    def task(n):
        with usage_scope(PRICES) as ledger:
            barrier.wait(timeout=5)
            for _ in range(n):
                tracked_create(fake_client(response()), 'generator', model=MODEL)
            barrier.wait(timeout=5)
            return ledger.summary()['llm_calls']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(task, [1, 3])) == [1, 3]
    with usage_scope(PRICES) as outer:
        with usage_scope(PRICES):
            tracked_create(fake_client(response()), 'generator', model=MODEL)
        assert outer.summary()['llm_calls'] == 0


def test_real_api_routes_with_fake_provider(store, monkeypatch):
    def generator(q, hits, *, model):
        payload = {'status': 'answered', 'reason': '', 'reason_citation_ids': [],
                   'claims': [{'statement': 'Whales communicate.', 'citation_ids': [hits[0]['chunk_id']]}]}
        return answer.call_openai(q, hits, model=model, client=fake_client(response(payload)))
    def planner(q, obs, *, model):
        return agent.call_agent_planner(q, obs, model=model, client=fake_client(response(decision('finish'))))
    real_answer = answer.answer_question
    real_agent = agent.run_research_agent
    monkeypatch.setattr(api, 'answer_question', lambda q, i, **kw: real_answer(q, i, generator=generator, **kw))
    monkeypatch.setattr(agent, 'run_research_agent', lambda q, i, **kw: real_agent(q, i, planner=planner, generator=generator, **kw))
    app = api.create_app(store=store)
    app.state.llm_prices = PRICES
    with TestClient(app) as client:
        payload = {'question': 'Whales communicate', 'model': MODEL}
        b = client.post('/ask', json=payload)
        a = client.post('/agent/ask', json=payload)
        assert b.status_code == a.status_code == 200
        assert b.json()['llm_usage']['llm_calls'] == 1
        assert a.json()['llm_usage']['llm_calls'] == 2
        assert a.json()['llm_usage']['estimated_cost_usd'] == pytest.approx(0.00241)
        no_hits = client.post('/ask', json={'question': 'zzunmatchableword'})
        assert no_hits.json()['llm_usage']['llm_calls'] == 0
        assert no_hits.json()['llm_usage']['estimated_cost_usd'] == 0
        metrics = client.get('/metrics').text
        assert 'marine_llm_calls_total{mode="baseline",response_status="completed",role="generator"} 1.0' in metrics
        assert 'marine_llm_calls_total{mode="agent",response_status="completed",role="planner"} 1.0' in metrics
        assert 'marine_llm_calls_total{mode="agent",response_status="completed",role="generator"} 1.0' in metrics


def test_http_502_still_exports_incomplete_usage(store, monkeypatch):
    real_answer = answer.answer_question
    def generator(q, hits, *, model):
        return answer.call_openai(q, hits, model=model, client=fake_client(response(status='incomplete')))
    monkeypatch.setattr(api, 'answer_question', lambda q, i, **kw: real_answer(q, i, generator=generator, **kw))
    app = api.create_app(store=store)
    app.state.llm_prices = PRICES
    with TestClient(app) as client:
        out = client.post('/ask', json={'question': 'Whales communicate'})
        assert out.status_code == 502
        metrics = client.get('/metrics').text
        assert 'marine_llm_calls_total{mode="baseline",response_status="incomplete",role="generator"} 1.0' in metrics
        assert 'marine_llm_estimated_cost_usd_total{mode="baseline",role="generator"} 0.001205' in metrics


def test_catalog_validation(tmp_path, monkeypatch):
    p = tmp_path / 'prices.json'
    monkeypatch.setenv('MARINE_LLM_PRICES_PATH', str(p))
    p.write_text('{"test":{"input":0.25,"cached_input":0.025,"output":2}}')
    assert load_prices()['test']['cached_input'] == Decimal('0.025')
    p.write_text('{"test":{"input":-1,"cached_input":0.025,"output":2}}')
    with pytest.raises(ValueError):
        load_prices()
