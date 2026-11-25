"""Sprint 4.4 regression tests with deterministic provider responses."""
import io
import json
from types import SimpleNamespace as NS
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from marine_evidence import answer, api, agent
from marine_evidence.llm_usage import usage_scope
from scripts import eval_agent_vs_ask as evaluation
from test_answer import HIT
from test_corpus_store import store  # noqa: F401
from test_llm_usage import MODEL, PRICES, response
from test_agent import decision


def payload(cid):
    return {'status': 'answered', 'reason': '', 'reason_citation_ids': [],
            'claims': [{'statement': 'Supported result.', 'citation_ids': [cid]}]}


def provider(*responses):
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return responses[len(calls) - 1]
    return NS(responses=NS(create=create)), calls


def test_dynamic_schema_isolated_and_constrains_both_arrays():
    other = {**HIT, 'chunk_id': 'P02:p0001:c0001'}
    for hit in (HIT, other):
        s = answer.answer_schema_for([hit, hit])['properties']
        assert s['claims']['items']['properties']['citation_ids']['items']['enum'] == [hit['chunk_id']]
        assert s['reason_citation_ids']['items']['enum'] == [hit['chunk_id']]
    assert 'enum' not in answer.ANSWER_SCHEMA['properties']['reason_citation_ids']['items']
    assert answer.answer_schema_for([])['properties']['reason_citation_ids']['maxItems'] == 0


@pytest.mark.parametrize('bad', [payload('P07:p0001:c0004'),
    {'status': 'insufficient_evidence', 'claims': [], 'reason': 'Missing.',
     'reason_citation_ids': ['FAKE:p1:c1']},
    {'status': 'answered', 'claims': [], 'reason': '', 'reason_citation_ids': []}])
def test_single_repair_uses_same_evidence_and_counts_both_calls(bad):
    client, calls = provider(response(bad), response(payload(HIT['chunk_id'])))
    with usage_scope(PRICES) as ledger:
        out = answer.call_openai('Question?', [HIT], model=MODEL, client=client)
        usage = ledger.summary()
    assert out['claims'][0]['citation_ids'] == [HIT['chunk_id']]
    assert len(calls) == usage['llm_calls'] == 2
    assert usage['estimated_cost_usd'] == pytest.approx(.00241)
    assert calls[0]['input'] == calls[1]['input']
    assert calls[0]['text'] == calls[1]['text']
    assert 'failed local output validation' in calls[1]['instructions']
    assert 'FAKE:p1:c1' not in calls[1]['instructions']


def test_second_invalid_answer_fails_closed():
    client, calls = provider(response(payload('bad')), response(payload('bad')))
    with usage_scope(PRICES) as ledger:
        with pytest.raises(answer.AnswerError, match='after one repair'):
            answer.call_openai('Question?', [HIT], model=MODEL, client=client)
        assert ledger.summary()['llm_calls'] == 2
    assert len(calls) == 2


def test_malformed_json_can_be_repaired():
    invalid = response(); invalid.output_text = '{'
    client, calls = provider(invalid, response(payload(HIT['chunk_id'])))
    assert answer.call_openai('Question?', [HIT], model=MODEL, client=client)['status'] == 'answered'
    assert len(calls) == 2


@pytest.mark.parametrize('kind', ['incomplete', 'empty'])
def test_provider_incomplete_or_empty_no_repair(kind):
    r = response(status='incomplete' if kind == 'incomplete' else 'completed')
    if kind == 'empty': r.output_text = ''
    client, calls = provider(r)
    with pytest.raises(answer.AnswerError):
        answer.call_openai('Question?', [HIT], model=MODEL, client=client)
    assert len(calls) == 1


@pytest.mark.parametrize('mode', ['baseline', 'agent'])
def test_error_response_preserves_usage_and_metrics(store, monkeypatch, mode):
    real_answer, real_agent = answer.answer_question, agent.run_research_agent
    client, calls = provider(response(payload('unknown')), response(payload('unknown')))
    def generator(q, hits, *, model):
        return answer.call_openai(q, hits, model=model, client=client)
    monkeypatch.setattr(api, 'answer_question', lambda q, i, **kw: real_answer(q, i, generator=generator, **kw))
    def planner(q, obs, *, model):
        return agent.call_agent_planner(q, obs, model=model, client=provider(response(decision('finish')))[0])
    monkeypatch.setattr(agent, 'run_research_agent', lambda q, i, **kw: real_agent(q, i, planner=planner, generator=generator, **kw))
    app = api.create_app(store=store); app.state.llm_prices = PRICES
    with TestClient(app) as tc:
        r = tc.post('/ask' if mode == 'baseline' else '/agent/ask', json={'question': 'Whales communicate', 'model': MODEL})
        assert r.status_code == 502
        body = r.json(); assert 'Unknown citation ID' in body['detail']
        assert body['llm_usage']['llm_calls'] == (2 if mode == 'baseline' else 3)
        assert body['llm_usage']['estimated_cost_usd'] == pytest.approx(.00241 if mode == 'baseline' else .003615)
        assert f'marine_llm_calls_total{{mode="{mode}",response_status="completed",role="generator"}} 2.0' in tc.get('/metrics').text


def test_evaluation_retains_error_usage(monkeypatch):
    body = {'detail': 'Invalid citation', 'llm_usage': {'llm_calls': 2, 'estimated_cost_usd': .005}}
    def fail(*a, **kw):
        raise HTTPError('http://localhost/ask', 502, 'Bad Gateway', {}, io.BytesIO(json.dumps(body).encode()))
    monkeypatch.setattr(evaluation.request, 'urlopen', fail)
    with pytest.raises(evaluation.ApiRequestError) as exc:
        evaluation.call_api('http://localhost/ask', {})
    assert exc.value.status_code == 502
    assert exc.value.llm_usage == body['llm_usage']
    assert exc.value.elapsed_seconds >= 0


def test_reviewed_pdf_unit_correction_is_opt_in_and_idempotent(tmp_path):
    from pathlib import Path
    from scripts.fix_p05_units import run, corrected_bytes
    root = Path(__file__).resolve().parents[1]
    pdf = root / 'papers/rspb20172314.pdf'
    if not pdf.is_file() or not (root / 'data/chunks/word_safe/chunks.jsonl').is_file():
        pytest.skip('Reviewed original P05 corpus not present')
    original = (root / 'data/chunks/word_safe/chunks.jsonl').read_bytes()
    # Both the original and already corrected corpus are allowed in subsequent tests.
    corrected, n = corrected_bytes(original)
    assert n in (0, 12)
    assert corrected_bytes(corrected)[1] == 0
    path = tmp_path / 'chunks.jsonl'
    path.write_bytes(original)
    assert run(pdf, path) == n and path.read_bytes() == original
    if n:
        assert run(pdf, path, apply=True) == n
        assert path.with_name(path.name + '.before_p05_unit_fix').read_bytes() == original
    assert run(pdf, path, apply=True) == 0
    before = [json.loads(l) for l in original.splitlines() if l.strip()]
    after = [json.loads(l) for l in path.read_bytes().splitlines() if l.strip()]
    for a, b in zip(before, after, strict=True):
        if a['source_id'] != 'P05': assert a == b
        else: assert {k:v for k,v in a.items() if k != 'text'} == {k:v for k,v in b.items() if k != 'text'}


def test_unit_correction_refuses_unreviewed_text_and_pdf(tmp_path):
    from pathlib import Path
    from scripts.fix_p05_units import corrected_bytes, run
    root = Path(__file__).resolve().parents[1]
    if not (root / 'data/chunks/word_safe/chunks.jsonl').is_file():
        pytest.skip('Reviewed original P05 corpus not present')
    raw = (root / 'data/chunks/word_safe/chunks.jsonl').read_bytes()
    rows = [json.loads(l) for l in raw.splitlines() if l.strip()]
    next(r for r in rows if r['chunk_id'] == 'P05:p0001:c0002')['text'] += ' changed'
    with pytest.raises(ValueError, match='hash changed'):
        corrected_bytes(('\n'.join(json.dumps(r) for r in rows)).encode())
    pdf = tmp_path / 'wrong.pdf'; pdf.write_bytes(b'not the source')
    chunks = tmp_path / 'chunks.jsonl'; chunks.write_bytes(raw)
    with pytest.raises(ValueError, match='PDF hash'):
        run(pdf, chunks, apply=True)
    assert chunks.read_bytes() == raw
