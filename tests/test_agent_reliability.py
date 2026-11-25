"""Sprint 4.2 regressions with real BM25 and deterministic model doubles."""
import pytest
from marine_evidence.agent import run_research_agent, MAX_EVIDENCE
from marine_evidence.answer import AnswerError, validate_answer, answer_question, render
from marine_evidence.bm25 import BM25Index
from test_agent import sample_index, decision, plan, generator, refusal
from test_answer import HIT, make_index
from test_corpus_store import store  # noqa: F401


def test_recover_unknown_and_duplicate_expansion_without_accessing_unretrieved():
    out = run_research_agent('blue whale', sample_index(), top_k=1,
        planner=plan(decision('expand_context', chunk_id='B:p1:c1'),
                     decision('expand_context', chunk_id='A:p1:c1'),
                     decision('expand_context', chunk_id='A:p1:c1'),
                     decision('finish')), generator=generator)
    assert out['status'] == 'answered'
    assert {h['source_id'] for h in out['retrieved']} == {'A'}
    assert out['trace'][1]['outcome'] == 'unknown_chunk_id'
    assert out['trace'][3]['outcome'] == 'duplicate_expansion'
    assert out['tool_calls'] == 2


def test_no_progress_finalizes_after_two_unproductive_actions():
    out = run_research_agent('blue whale', sample_index(), top_k=1,
        planner=plan(decision('search_bm25', query='absenttokenone'),
                     decision('search_bm25', query='absenttokentwo')), generator=generator)
    assert out['stop_reason'] == 'no_progress' and out['status'] == 'answered'
    assert out['steps'] == 2 and out['tool_calls'] == 3


def test_evidence_limit_finalizes_without_extra_planner_call():
    chunks = []
    for i in range(MAX_EVIDENCE + 5):
        chunks.append({**HIT, 'chunk_id': f'P01:p0001:c{i:04}',
                       'text': 'alpha' if i < 6 else 'beta'})
    out = run_research_agent('alpha', BM25Index(chunks), top_k=6,
        planner=plan(decision('search_bm25', query='beta')), generator=generator)
    assert out['status'] == 'answered' and out['stop_reason'] == 'evidence_limit'
    assert len(out['retrieved']) == MAX_EVIDENCE and out['steps'] == 1


def test_invalid_action_never_executes_and_can_recover():
    out = run_research_agent('blue whale', sample_index(),
        planner=plan(decision('delete_document'), decision('finish')), generator=generator)
    assert out['trace'][1]['action'] == 'invalid_decision'
    assert out['trace'][1]['outcome'] == 'invalid_decision'
    assert out['tool_calls'] == 1 and out['status'] == 'answered'


def test_transport_failure_not_relabelled_as_abstention():
    def failing(*args, **kwargs):
        raise AnswerError('API transport failure')
    with pytest.raises(AnswerError, match='transport'):
        run_research_agent('blue whale', sample_index(), planner=failing, generator=generator)


def test_no_evidence_no_generator_after_no_progress():
    out = run_research_agent('unmatchedtoken', sample_index(),
        planner=plan(decision('search_bm25', query='absenttokenone'),
                     decision('search_bm25', query='absenttokentwo')),
        generator=lambda *a, **kw: pytest.fail('No evidence'))
    assert out['status'] == 'insufficient_evidence' and out['stop_reason'] == 'no_progress'


def partial(q, hits, *, model):
    cid = hits[0]['chunk_id']
    return {'status': 'partially_answered',
            'claims': [{'statement': 'Supported result.', 'citation_ids': [cid]}],
            'reason': 'The second study is missing.', 'reason_citation_ids': [cid]}


@pytest.mark.parametrize('agent', [False, True])
def test_partial_output_preserves_claims_and_reason_citations(agent):
    if agent:
        out = run_research_agent('vessel noise', make_index(), planner=plan(decision('finish')), generator=partial)
    else:
        out = answer_question('vessel noise', make_index(), generator=partial)
    assert out['status'] == 'partially_answered' and len(out['claims']) == 1
    assert out['reason_citation_ids'] == [HIT['chunk_id']]
    assert len(out['citations']) == 1
    assert 'PARTIALLY ANSWERED' in render(out)


def test_refusal_reason_citations_resolve_into_source_metadata():
    out = answer_question('vessel noise', make_index(), generator=lambda *a, **kw: {
        'status': 'insufficient_evidence', 'claims': [], 'reason': 'No threshold provided.',
        'reason_citation_ids': [HIT['chunk_id']]})
    assert out['citations'][0]['chunk_id'] == HIT['chunk_id']
    assert '[P01 p.1]' in render(out)


@pytest.mark.parametrize('reason,refs', [('Missing.', ['FAKE:p1:c1']),
    ('See P05:p0002:c3.', []), ('See P01:p0001:c0001.', [])])
def test_invalid_or_inline_reason_references_rejected(reason, refs):
    with pytest.raises(AnswerError):
        validate_answer({'status': 'insufficient_evidence', 'claims': [], 'reason': reason,
                         'reason_citation_ids': refs}, [HIT])


@pytest.mark.parametrize('claims,reason', [([], 'Missing.'),
    ([{'statement': 'Result.', 'citation_ids': [HIT['chunk_id']]}], '')])
def test_partial_requires_claims_and_gap(claims, reason):
    with pytest.raises(AnswerError):
        validate_answer({'status': 'partially_answered', 'claims': claims, 'reason': reason,
                         'reason_citation_ids': []}, [HIT])


def test_partial_agent_api_and_metrics(monkeypatch, store):
    from fastapi.testclient import TestClient
    from marine_evidence import agent
    from marine_evidence.api import create_app
    real_run = agent.run_research_agent
    monkeypatch.setattr(agent, 'run_research_agent', lambda q, idx, **kw: real_run(
        q, idx, planner=plan(decision('expand_context', chunk_id='UNKNOWN:p1:c1'),
                             decision('finish')), generator=partial, **kw))
    with TestClient(create_app(store=store)) as client:
        response = client.post('/agent/ask', json={'question': 'Whales communicate underwater'})
        assert response.status_code == 200, response.text
        out = response.json()
        assert out['status'] == 'partially_answered'
        assert out['reason_citation_ids'] == [out['citations'][0]['chunk_id']]
        assert out['trace'][1]['outcome'] == 'unknown_chunk_id'
        assert out['tool_calls'] == 1
        metrics = client.get('/metrics').text
        assert 'marine_agent_runs_total{outcome="partially_answered",stop_reason="agent_finished"} 1.0' in metrics
        assert 'marine_agent_tool_calls_total{tool="search_bm25"} 1.0' in metrics
        assert 'marine_agent_tool_calls_total{tool="expand_context"}' not in metrics
