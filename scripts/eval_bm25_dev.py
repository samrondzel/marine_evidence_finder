"""Evaluate BM25 retrieval against *dev* labels only. Holdout test is untouched.

Usage: python scripts/eval_bm25_dev.py --top-k 5
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys

from marine_evidence.bm25 import BM25Index, read_chunks


def evaluate(index: BM25Index, rows: list[dict], *, top_k: int = 5,
             distinct_pages: bool = False) -> tuple[list[dict], dict]:
    # Guard against accidental benchmark-leakage: explicitly discard test labels.
    dev = [r for r in rows if r["split"] == "dev"]
    if not dev:
        raise ValueError("No dev questions found")
    predictions = []
    stats = []
    for record in dev:
        hits = index.search(record["question"], top_k=top_k,
                            distinct_pages=distinct_pages)
        predictions.append({
            "id": record["id"],
            "question": record["question"],
            "retrieved": [{"chunk_id": h["chunk_id"], "source_id": h["source_id"],
                           "pdf_page": h["pdf_page"], "score": h["score"]} for h in hits],
        })
        # Unsupported questions are NOT scored as retrieval errors; retrieval
        # cannot alone determine that no answer is available in the corpus.
        if record["answerability"] != "answerable":
            stats.append({"id": record["id"], "type": record["task_type"],
                          "source_recall": None, "page_recall": None})
            continue
        gold_sources = set(record["source_ids"])
        # Per benchmark: only direct supports count, not 'limitation' or 'scope'.
        gold_pages = {(ev["source_id"], ev["pdf_page"]) for ev in record["evidence"]
                      if ev["evidence_role"] not in ("scope", "limitation")}
        if not gold_sources or not gold_pages:
            raise ValueError(f"No gold sources or direct pages for {record['id']}")
        found_sources = {h["source_id"] for h in hits}
        found_pages = {(h["source_id"], h["pdf_page"]) for h in hits}
        stats.append({"id": record["id"], "type": record["task_type"],
                      "source_recall": len(found_sources & gold_sources) / len(gold_sources),
                      "page_recall": len(found_pages & gold_pages) / len(gold_pages),
                      "gold_pages": [f"{s}:p{p}" for s,p in sorted(gold_pages)],
                      "found_pages": [f"{s}:p{p}" for s,p in sorted(found_pages & gold_pages)]})
    ans = [s for s in stats if s["source_recall"] is not None]
    summary = {"split": "dev", "questions": len(dev), "answerable_scored": len(ans),
               "unsupported_not_scored": len(dev)-len(ans), "top_k": top_k,
               "distinct_pages": distinct_pages,
               "mean_source_recall": statistics.mean(s["source_recall"] for s in ans),
               "mean_direct_page_recall": statistics.mean(s["page_recall"] for s in ans),
               "per_question": stats,
               "notes": "Dev only. Page recall uses direct supporting page labels, not exact passage match. Not answer faithfulness or abstention accuracy."}
    return predictions, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate BM25 on dev split (never test)")
    parser.add_argument("--chunks", type=Path, default=Path("data/chunks/fixed/chunks.jsonl"))
    parser.add_argument("--benchmark", type=Path, default=Path("evaluation/benchmark_v1.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/evaluation/bm25_dev"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--distinct-pages", action="store_true")
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be positive")
    try:
        rows = [json.loads(l) for l in args.benchmark.read_text(encoding="utf-8").splitlines() if l.strip()]
        index = BM25Index(read_chunks(args.chunks))
        preds, summary = evaluate(index, rows, top_k=args.top_k, distinct_pages=args.distinct_pages)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "predictions_dev.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in preds),encoding="utf-8")
    (args.out_dir / "metrics_dev.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(f"BM25 baseline | {index.n_docs} chunks | dev: {summary['questions']} questions, "
          f"{summary['answerable_scored']} answerable, {summary['unsupported_not_scored']} unsupported")
    for item in summary["per_question"]:
        if item["source_recall"] is None:
            print(f"  {item['id']} [{item['type']}] N/A (abstention, needs separate QA evaluation)")
        else:
            print(f"  {item['id']} [{item['type']}] source={item['source_recall']:.2f} "
                  f"direct-page={item['page_recall']:.2f}")
    print(f"\nDEV mean source recall@{args.top_k}: {summary['mean_source_recall']:.3f}")
    print(f"DEV mean direct evidence page recall@{args.top_k}: {summary['mean_direct_page_recall']:.3f}")
    print(f"Reports saved to {args.out_dir}")


if __name__ == "__main__":
    main()
