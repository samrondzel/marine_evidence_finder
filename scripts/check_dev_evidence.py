"""Check source text continuity against *dev-only* annotations.

This checks ingestion quality, NOT retrieval quality. The test split is not read.
"""
import argparse
import json
import unicodedata
from pathlib import Path


def key(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


parser = argparse.ArgumentParser()
parser.add_argument("--pages", type=Path, default=Path("data/processed/pages.jsonl"))
parser.add_argument("--benchmark", type=Path, default=Path("evaluation/benchmark_v1.jsonl"))
args = parser.parse_args()

pages = {}
with args.pages.open(encoding="utf-8") as handle:
    for raw in handle:
        item = json.loads(raw)
        pages[(item["source_id"], item["pdf_page"])] = key(item["text"])

seen = matches = 0
missing = []
with args.benchmark.open(encoding="utf-8") as handle:
    for raw in handle:
        question = json.loads(raw)
        if question["split"] != "dev":
            continue  # Test split is held out from all tuning.
        for evidence in question["evidence"]:
            seen += 1
            source = evidence["source_id"]
            page = evidence["pdf_page"]
            if key(evidence["quote"]) in pages.get((source, page), ""):
                matches += 1
            else:
                missing.append(f"{question['id']}: {source} p{page}")

print(f"DEV evidence continuity: {matches}/{seen} exact normalized excerpts preserved")
if missing:
    print("Not contiguous (inspect layout or normalization; not necessarily missing content):")
    for item in missing:
        print(" -", item)
