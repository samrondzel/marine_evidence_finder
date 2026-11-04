"""Inspect chunks for one PDF source and page."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--chunks", type=Path, default=Path("data/chunks/fixed/chunks.jsonl"))
parser.add_argument("--source", required=True)
parser.add_argument("--page", type=int, required=True)
parser.add_argument("--limit", type=int, default=3)
args = parser.parse_args()

num = 0
for line in args.chunks.read_text(encoding="utf-8").splitlines():
    c = json.loads(line)
    if c["source_id"] == args.source and c["pdf_page"] == args.page:
        print(f"\n--- {c['chunk_id']} | page {c['pdf_page']} "
              f"| chars {c['start_char']}:{c['end_char']} | words={c['word_count']} ---")
        print(c["text"][:800])
        num += 1
        if num >= args.limit:
            break
if not num:
    raise SystemExit("No chunks for that source/page")
