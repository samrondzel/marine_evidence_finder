"""Compare BM25 and local semantic retrieval using only development labels.

The dense index and BM25 consume the very same chunk JSONL. Benchmark labels
are used only to evaluate ranking, never to create embeddings or tune weights.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from marine_evidence.bm25 import BM25Index, read_chunks, SearchError
from marine_evidence.semantic import open_index
from scripts.eval_bm25_dev import evaluate


def compare(chunks_path: Path, index_dir: Path, benchmark_path: Path, *, top_k: int = 5,
            distinct_pages: bool = False, encoder=None) -> dict:
    chunks = read_chunks(chunks_path)
    semantic, meta = open_index(chunks_path, index_dir, encoder=encoder)
    lexical = BM25Index(chunks)
    rows = [json.loads(line) for line in benchmark_path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    bm_preds, bm = evaluate(lexical, rows, top_k=top_k, distinct_pages=distinct_pages)
    se_preds, se = evaluate(semantic, rows, top_k=top_k, distinct_pages=distinct_pages)
    bm_by_id = {p["id"]: p for p in bm["per_question"]}
    se_by_id = {p["id"]: p for p in se["per_question"]}
    per_question = []
    for qid, old in bm_by_id.items():
        new = se_by_id[qid]
        per_question.append({
            "id": qid,
            "task_type": old["type"],
            "bm25_source_recall": old["source_recall"],
            "bm25_page_recall": old["page_recall"],
            "semantic_source_recall": new["source_recall"],
            "semantic_page_recall": new["page_recall"],
            "page_delta": None if old["page_recall"] is None else round(new["page_recall"]-old["page_recall"], 6),
            "gold_pages": old.get("gold_pages", []),
            "bm25_found_pages": old.get("found_pages", []),
            "semantic_found_pages": new.get("found_pages", []),
        })
    return {
        "split": "dev",
        "top_k": top_k,
        "chunk_count": len(chunks),
        "model": meta["model_name"],
        "distinct_pages": distinct_pages,
        "bm25": {"mean_source_recall": bm["mean_source_recall"],
                 "mean_direct_page_recall": bm["mean_direct_page_recall"]},
        "semantic": {"mean_source_recall": se["mean_source_recall"],
                     "mean_direct_page_recall": se["mean_direct_page_recall"]},
        "per_question": per_question,
        "predictions_bm25": bm_preds,
        "predictions_semantic": se_preds,
        "note": "DEV only; source/page retrieval metrics. Not exact quote recall, answer faithfulness, or hallucination rate.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fair dev-only retrieval comparison on identical chunks")
    parser.add_argument("--chunks", type=Path, default=Path("data/chunks/word_safe/chunks.jsonl"))
    parser.add_argument("--index-dir", type=Path, default=Path("data/index/e5_small_v2_word_safe"))
    parser.add_argument("--benchmark", type=Path, default=Path("evaluation/benchmark_v1.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/evaluation/compare_dev_e5_word_safe"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--distinct-pages", action="store_true")
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be positive")
    try:
        result = compare(args.chunks, args.index_dir, args.benchmark, top_k=args.top_k,
                         distinct_pages=args.distinct_pages)
    except (OSError, ValueError, SearchError, KeyError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir/"metrics_dev.json").write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    for method in ("bm25", "semantic"):
        path = args.out_dir / f"predictions_{method}_dev.jsonl"
        path.write_text("".join(json.dumps(x, ensure_ascii=False)+"\n" for x in result[f"predictions_{method}"]), encoding="utf-8")
    print(f"DEV only | {result['chunk_count']} identical chunks | top-{result['top_k']} | model={result['model']}")
    print("Method       SourceRecall  EvidencePageRecall")
    for key in ("bm25", "semantic"):
        m = result[key]
        print(f"{key:12s} {m['mean_source_recall']:12.3f} {m['mean_direct_page_recall']:19.3f}")
    print("\nPer question (page recall):")
    for item in result["per_question"]:
        if item["bm25_page_recall"] is not None:
            print(f"  {item['id']}: BM25={item['bm25_page_recall']:.2f}  "
                  f"semantic={item['semantic_page_recall']:.2f}  delta={item['page_delta']:+.2f}")
    q13 = next((x for x in result["per_question"] if x["id"] == "Q13"), None)
    if q13:
        print(f"\nQ13 gold: {q13['gold_pages']}")
        print(f"Q13 BM25 hit: {q13['bm25_found_pages']}")
        print(f"Q13 semantic hit: {q13['semantic_found_pages']}")
    print(f"\nResults: {args.out_dir}")


if __name__ == "__main__":
    main()
