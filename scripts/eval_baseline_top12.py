"""Optional paid comparison of baseline /ask vs bounded /agent/ask.

Gold annotations are used ONLY AFTER receiving model results, never sent to LLM.
Scientific correctness/entailment still needs manual review.

  python scripts/eval_agent_vs_ask.py --confirm-paid --split dev --limit 3
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib import request, error


def call_api(url: str, payload: dict) -> tuple[dict, float]:
    body = json.dumps(payload).encode('utf-8')
    req = request.Request(url, data=body,
                          headers={'Content-Type': 'application/json'}, method='POST')
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=280) as response:
            result = json.load(response)
    except error.HTTPError as exc:
        raise RuntimeError(f'HTTP {exc.code}: {exc.read().decode()[:300]}') from exc
    return result, time.perf_counter() - started


def source_recall(output: dict, gold: set[str]) -> float | None:
    if not gold:
        return None
    retrieved = {x['source_id'] for x in output.get('retrieved', [])}
    return round(len(retrieved & gold) / len(gold), 3)


def main():
    p = argparse.ArgumentParser(description='Compare cited answer vs agent; makes paid OpenAI API calls')
    p.add_argument('--confirm-paid', action='store_true', help='Required: explicitly allow API token charges')
    p.add_argument('--benchmark', type=Path, default=Path('evaluation/benchmark_v1.jsonl'))
    p.add_argument('--split', choices=('dev', 'test'), default='dev')
    p.add_argument('--limit', type=int, default=3)
    p.add_argument('--model', default='gpt-5-mini')
    p.add_argument('--url', default='http://127.0.0.1:8000')
    p.add_argument('--output', type=Path, help='Optional JSONL results to manually grade (avoid public sharing)')
    args = p.parse_args()
    if not args.confirm_paid:
        p.error('Add --confirm-paid; this runs BOTH /ask and /agent/ask via external LLM API')
    if not 1 <= args.limit <= 20:
        p.error('--limit must be between 1 and 20')
    cases = [json.loads(line) for line in args.benchmark.read_text(encoding='utf-8').splitlines()
             if line.strip()]
    cases = [c for c in cases if c['split'] == args.split][:args.limit]
    if not cases:
        p.error('No benchmark questions for requested split')
    records = []
    for case in cases:
        print(f"{case['id']} {case['task_type']}: {case['question']}")
        row = {'question_id': case['id'], 'split': case['split'],
               'gold_answerability': case['answerability'], 'question': case['question']}
        for name, endpoint, extra in [('baseline', '/ask', {'top_k': 12})]:
            try:
                out, seconds = call_api(args.url.rstrip('/') + endpoint,
                                        {'question': case['question'], 'model': args.model, **extra})
                info = {
                    'status': out['status'],
                    'elapsed_seconds': round(seconds, 2),
                    'source_recall': source_recall(out, set(case.get('source_ids', [])))
                        if case['answerability'] == 'answerable' else None,
                    'citations': out.get('citations', []),
                    'claims': out.get('claims', []),
                    'reason': out.get('reason', ''),
                    'reason_citation_ids': out.get('reason_citation_ids', []),
                    'stop_reason': out.get('stop_reason'),
                    'retrieved': out.get('retrieved', []),
                    'steps': out.get('steps'),
                    'tool_calls': out.get('tool_calls'),
                    'trace': out.get('trace', []),
                }
                print(f"  {name:<8} {out['status']:<23} {seconds:>5.1f}s ",
                      f"recall={info['source_recall']} tools={info['tool_calls']}")
                row[name] = info
            except (RuntimeError, TimeoutError, error.URLError) as exc:
                print(f'  {name:<8} ERROR: {type(exc).__name__}: {exc}')
                row[name] = {'error': str(exc)}
        records.append(row)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records),
                               encoding='utf-8')
        print('Saved comparison records:', args.output)
    print('NOTE: source recall is only a retrieval proxy; manually grade factual correctness,')
    print('unsupported claims, abstention and overall cost. Gold answers never entered model prompts.')


if __name__ == '__main__':
    main()
