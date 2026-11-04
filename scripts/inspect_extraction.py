"""Print one extracted page and show why page-level traceability matters."""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--pages", type=Path, default=Path("data/processed/pages.jsonl"))
p.add_argument("--source", default="P01")
p.add_argument("--page", type=int, default=3)
p.add_argument("--limit", type=int, default=2500)
args = p.parse_args()

with args.pages.open(encoding="utf-8") as inp:
    for line in inp:
        rec = json.loads(line)
        if rec["source_id"] == args.source and rec["pdf_page"] == args.page:
            print(f"{rec['source_id']} | {rec['title']} | PDF page {rec['pdf_page']}")
            print("=" * 55)
            print(rec["text"][:args.limit])
            break
    else:
        p.error(f"Page not found: {args.source}, {args.page}")
