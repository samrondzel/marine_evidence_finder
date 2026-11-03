#!/usr/bin/env python3
import argparse, hashlib, json, pathlib, sys, unicodedata, collections
import fitz
P=argparse.ArgumentParser();P.add_argument('--papers-dir',required=True);a=P.parse_args()
base=pathlib.Path(__file__).resolve().parent;pdfroot=pathlib.Path(a.papers_dir)
manifest=json.loads((base/'papers_manifest.json').read_text(encoding='utf8'))
qa=[json.loads(l) for l in (base/'benchmark_v1.jsonl').read_text(encoding='utf8').splitlines() if l.strip()]
errors=[];titles={m['id']:m for m in manifest};seen={};pages={};types=collections.Counter()
for m in manifest:
 f=pdfroot/m['local_pdf_filename']
 if not f.exists():errors.append(f"Missing PDF: {f}");continue
 if hashlib.sha256(f.read_bytes()).hexdigest()!=m['sha256']:errors.append(f"SHA-256 mismatch: {f}")
 d=fitz.open(f)
 if len(d)!=m['pdf_page_count']:errors.append(f"Page count mismatch: {f}")
 for j,p in enumerate(d,1):
  t=unicodedata.normalize('NFKC',p.get_text()).replace('\u00ad','').replace('\xa0',' ').replace('\ufeff','')
  pages[m['id'],j]=' '.join(t.split())
print(f'PDFs: {len(manifest)}; Questions: {len(qa)}')
for q in qa:
 types[q['task_type']]+=1
 if q['id'] in seen:errors.append('Duplicate question '+q['id'])
 seen[q['id']]=True
 if not q['required_facts']:errors.append('Missing required facts '+q['id'])
 if q['task_type'] not in ('fact','synthesis','abstention'):errors.append('Unknown question type '+q['id'])
 if set(q['source_ids'])!=set(e['source_id'] for e in q['evidence']):errors.append('Missing source evidence '+q['id'])
 for e in q['evidence']:
  k=(e['source_id'],e['pdf_page'])
  if k not in pages:errors.append(f"Source/page missing: {q['id']}: {k}")
  elif e['quote'] not in pages[k]:errors.append(f"Evidence not found verbatim: {q['id']}: {k}: {e['quote'][:70]}")
print('Question distribution:',dict(types))
if errors:
 print('FAIL: '+str(len(errors))+' checks failed')
 for e in errors:print(' -',e)
 sys.exit(1)
print('PASS: All evidence spans and checksums verified.')
