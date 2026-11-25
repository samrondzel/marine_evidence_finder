"""Sprint 4 smoke: offline deterministic agent; --live makes REAL paid LLM calls.

Examples:
  python scripts/smoke_agent.py
  python scripts/smoke_agent.py --live --question "How does vessel noise affect marine mammals?"
"""
from __future__ import annotations

import argparse
import json
import os
from urllib import error, request

from marine_evidence.agent import run_research_agent
from marine_evidence.bm25 import BM25Index


def offline() -> None:
    chunks = [
        {'chunk_id': 'S:p1:c1', 'source_id': 'S', 'pdf_page': 1,
         'title': 'Acoustics sample', 'filename': 'sample.pdf', 'doi': '',
         'text': 'Underwater hydrophones recorded blue whale vocalizations near ships.'},
        {'chunk_id': 'S:p1:c2', 'source_id': 'S', 'pdf_page': 1,
         'title': 'Acoustics sample', 'filename': 'sample.pdf', 'doi': '',
         'text': 'This short passage describes data collection, not causal effects.'},
    ]
    index = BM25Index(chunks)
    def planner(question, obs, *, model):
        actions = [
            ('search_bm25', 'blue whale vocalizations', ''),
            ('expand_context', '', 'S:p1:c1'),
            ('finish', '', ''),
        ]
        action, query, cid = actions[obs['step'] - 1]
        return {'action': action, 'query': query, 'chunk_id': cid,
                'note': 'Deterministic test action'}
    def generator(question, hits, *, model):
        return {'status': 'answered', 'reason': '', 'claims': [
            {'statement': 'Hydrophones recorded blue whale vocalizations.',
             'citation_ids': [hits[0]['chunk_id']]},
        ]}
    result = run_research_agent('What did hydrophones record?', index,
                                planner=planner, generator=generator)
    assert result['status'] == 'answered'
    assert result['steps'] == 3 and result['tool_calls'] == 3
    assert result['trace'][0]['step'] == 0
    assert result['trace'][0]['origin'] == 'original_question'
    assert result['trace'][0]['query'] == 'What did hydrophones record?'
    assert result['citations'][0]['source_id'] == 'S'
    print('PASS: exact original question -> BM25 -> bounded planner -> context -> cited answer')
    print('Trace:', json.dumps(result['trace'], indent=2, ensure_ascii=False))
    print('This OFFLINE smoke does not test the Docker API or OpenAI credentials.')


def live(base_url: str, question: str, model: str) -> None:
    if not os.environ.get('OPENAI_API_KEY'):
        print('NOTE: the key is read by Docker API from .env, not from this shell.')
    data = json.dumps({'question': question, 'model': model,
                       'max_steps': 5, 'top_k': 4}).encode('utf-8')
    req = request.Request(base_url.rstrip('/') + '/agent/ask', data=data,
                          headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with request.urlopen(req, timeout=270) as response:
            result = json.load(response)
    except error.HTTPError as exc:
        raise SystemExit(f'LIVE agent returned HTTP {exc.code}: {exc.read().decode()[:600]}') from exc
    print(json.dumps({k: result[k] for k in ('status', 'reason', 'reason_citation_ids', 'stop_reason',
                                            'steps', 'tool_calls', 'claims', 'citations', 'trace', 'llm_usage')},
                     indent=2, ensure_ascii=False))
    assert result['steps'] <= 5 and result['tool_calls'] <= result['steps'] + 1
    assert result['trace'][0]['step'] == 0 and result['trace'][0]['origin'] == 'original_question'
    assert result['trace'][0]['query'] == question
    assert all(c['chunk_id'] in {h['chunk_id'] for h in result['retrieved']}
               for c in result['citations'])
    usage = result['llm_usage']
    assert usage['llm_calls'] == len(usage['calls'])
    assert sum(c['role'] == 'planner' for c in usage['calls']) == result['steps']
    generators = sum(c['role'] == 'generator' for c in usage['calls'])
    assert generators in ((1, 2) if result['retrieved'] else (0,))
    print('PASS: live /agent/ask returned a bounded, citation-checked result')
    print('NOTE: supported citation IDs do not prove scientific entailment.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Opt in to REAL OpenAI requests and charges')
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--question', default='What evidence describes marine mammal responses to vessel noise?')
    parser.add_argument('--model', default='gpt-5-mini')
    args = parser.parse_args()
    if args.live:
        live(args.url, args.question, args.model)
    else:
        offline()


if __name__ == '__main__':
    main()
