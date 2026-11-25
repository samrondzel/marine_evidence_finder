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


class ApiRequestError(RuntimeError):
    def __init__(self, status_code: int, body: dict, elapsed_seconds: float):
        self.status_code = status_code
        self.llm_usage = body.get('llm_usage')
        self.elapsed_seconds = elapsed_seconds
        super().__init__(f"HTTP {status_code}: {str(body.get('detail', 'Unknown error'))[:300]}")


def call_api(url: str, payload: dict) -> tuple[dict, float]:
    body = json.dumps(payload).encode('utf-8')
    req = request.Request(url, data=body,
                          headers={'Content-Type': 'application/json'}, method='POST')
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=280) as response:
            result = json.load(response)
    except error.HTTPError as exc:
        raw = exc.read().decode('utf-8', errors='replace')
        try:
            body = json.loads(raw)
            if not isinstance(body, dict):
                body = {'detail': raw[:300]}
        except ValueError:
            body = {'detail': raw[:300]}
        raise ApiRequestError(exc.code, body, time.perf_counter() - started) from exc
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
    p.add_argument('--mode', choices=('both', 'baseline', 'agent'), default='both')
    p.add_argument('--baseline-top-k', type=int, choices=range(1, 21), default=4)
    p.add_argument('--question-id', action='append', help='Select exact question ID(s) within split before limit')
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
    cases = [c for c in cases if c['split'] == args.split and
             (not args.question_id or c['id'] in args.question_id)][:args.limit]
    if not cases:
        p.error('No benchmark questions for requested split')
    configs = [('baseline', '/ask', {'top_k': args.baseline_top_k}),
               ('agent', '/agent/ask', {'top_k': 4, 'max_steps': 5})]
    configs = [c for c in configs if args.mode == 'both' or c[0] == args.mode]
    records = []
    for case in cases:
        print(f"{case['id']} {case['task_type']}: {case['question']}")
        row = {'question_id': case['id'], 'split': case['split'],
               'gold_answerability': case['answerability'], 'question': case['question']}
        for name, endpoint, extra in configs:
            try:
                out, seconds = call_api(args.url.rstrip('/') + endpoint,
                                        {'question': case['question'], 'model': args.model, **extra})
                info = {
                    'status': out['status'],
                    'llm_usage': out.get('llm_usage'),
                    'parameters': {'model': args.model, **extra},
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
                usage = info['llm_usage'] or {}
                cost = usage.get('estimated_cost_usd')
                print(f"    LLM calls={usage.get('llm_calls')} input={usage.get('input_tokens')} "
                      f"output={usage.get('output_tokens')} reasoning={usage.get('reasoning_tokens')} "
                      f"estimated USD={cost:.6f}" if cost is not None else
                      '    LLM cost unknown (see llm_usage in JSONL)')
                row[name] = info
            except ApiRequestError as exc:
                print(f'  {name:<8} ERROR: {exc}')
                row[name] = {'status': 'error', 'error': str(exc), 'http_status': exc.status_code,
                             'elapsed_seconds': round(exc.elapsed_seconds, 2),
                             'parameters': {'model': args.model, **extra}, 'llm_usage': exc.llm_usage}
                cost = (exc.llm_usage or {}).get('estimated_cost_usd')
                print(f'    Failed request estimated USD={cost:.6f}' if cost is not None else
                      '    Failed request cost unknown')
            except (RuntimeError, TimeoutError, error.URLError) as exc:
                print(f'  {name:<8} ERROR: {type(exc).__name__}: {exc}')
                row[name] = {'status': 'error', 'error': str(exc), 'llm_usage': None,
                             'parameters': {'model': args.model, **extra}}
        records.append(row)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records),
                               encoding='utf-8')
        print('Saved comparison records:', args.output)
    for name, _, _ in configs:
        usages = [(r.get(name) or {}).get('llm_usage') for r in records]
        costs = [u['estimated_cost_usd'] for u in usages if u and u.get('estimated_cost_usd') is not None]
        known = sum(u.get('known_cost_usd', 0) for u in usages if u)
        print(f'{name}: priced results {len(costs)}/{len(records)}; known estimated USD={known:.6f}')
    print('NOTE: source recall is only a retrieval proxy; manually grade factual correctness,')
    print('unsupported claims, abstention and overall cost. Gold answers never entered model prompts.')


if __name__ == '__main__':
    main()
