#!/usr/bin/env python3
"""Grade PDF source/page coverage for retrieval predictions. No automatic truthfulness grading."""
import argparse,json,pathlib,statistics,sys
p=argparse.ArgumentParser();p.add_argument('--predictions',required=True);p.add_argument('--k',type=int,default=5);args=p.parse_args()
base=pathlib.Path(__file__).resolve().parent
q=[json.loads(l) for l in (base/'benchmark_v1.jsonl').read_text(encoding='utf8').splitlines() if l.strip()]
rows=[json.loads(l) for l in pathlib.Path(args.predictions).read_text(encoding='utf8').splitlines() if l.strip()]
byid={r['id']:r for r in rows};bad=[];scored=[]
for x in q:
 if x['id'] not in byid:continue
 pred=byid[x['id']];retr=pred.get('retrieved',[])[:args.k]
 gold_src=set(x['source_ids']);pred_src={z['source_id'] for z in retr}
 gold_page={(z['source_id'],z['pdf_page']) for z in x['evidence'] if z['evidence_role'] not in ('scope','limitation')}
 pred_page={(z['source_id'],z['pdf_page']) for z in retr}
 src_recall=(len(gold_src&pred_src)/len(gold_src)) if x['answerability']=='answerable' and gold_src else None
 # Only score direct supporting evidence for answerable questions, not abstention scope notes
 page_recall=(len(gold_page&pred_page)/len(gold_page)) if x['answerability']=='answerable' and gold_page else None
 scored.append((x['id'],x['task_type'],src_recall,page_recall))
 print(f"{x['id']} [{x['task_type']}]: source-recall@{args.k}={src_recall if src_recall is not None else 'N/A'}, direct-page-recall={page_recall if page_recall is not None else 'N/A'}")
for k,idx in [('source',2),('direct evidence page',3)]:
 vals=[r[idx] for r in scored if r[idx] is not None]
 print(f'{k} recall@{args.k}: '+(f'{statistics.mean(vals):.3f} (n={len(vals)})' if vals else 'N/A'))
missing=len(q)-len(scored)
print(f'Predictions processed: {len(scored)}/{len(q)}; missing={missing}')
if missing:sys.exit(2)
