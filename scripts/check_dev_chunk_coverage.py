"""Development-only diagnostic: does an annotated evidence excerpt fit in a chunk?

NOT a retrieval metric: a chunk containing evidence may still rank very poorly.
Never reads held-out test annotations. Does not load answers into the index.
"""
from __future__ import annotations
import argparse
import json
from collections import defaultdict
from pathlib import Path
import unicodedata


def normalized(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--chunks", type=Path, default=Path("data/chunks/fixed/chunks.jsonl"))
    p.add_argument("--benchmark", type=Path, default=Path("evaluation/benchmark_v1.jsonl"))
    a = p.parse_args()
    chunks = defaultdict(list)
    with a.chunks.open(encoding="utf-8") as file:
        for line in file:
            item = json.loads(line)
            chunks[(item["source_id"], item["pdf_page"])].append((item["chunk_id"], normalized(item["text"])))
    hits = total = 0
    failures = []
    with a.benchmark.open(encoding="utf-8") as file:
        for line in file:
            question = json.loads(line)
            if question["split"] != "dev":
                continue
            for evidence in question["evidence"]:
                total += 1
                quote = normalized(evidence["quote"])
                possible = chunks.get((evidence["source_id"], evidence["pdf_page"]), [])
                if any(quote in chunk_text for _, chunk_text in possible):
                    hits += 1
                else:
                    failures.append(f"{question['id']} {evidence['source_id']} p{evidence['pdf_page']}")
    print(f"DEV evidence-contained-in-single-chunk: {hits}/{total}")
    if failures:
        print("Misses (may require overlap/size changes or improved PDF parsing):")
        for item in failures:
            print(" -", item)
    print("NOTE: This is a chunk coverage diagnostic, not Recall@k or answer accuracy.")


if __name__ == "__main__":
    main()
