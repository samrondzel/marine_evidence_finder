"""DEV-only BM25 vs semantic vs weighted-RRF; never accesses the held-out test labels."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from marine_evidence.bm25 import BM25Index, read_chunks, SearchError
from marine_evidence.hybrid import HybridIndex
from marine_evidence.semantic import open_index
from scripts.eval_bm25_dev import evaluate


def compare(chunks_path: Path, index_dir: Path, benchmark_path: Path, *,
            top_k: int = 5, bm25_weight: float = 0.75, candidate_k: int = 40,
            distinct_pages: bool = False, encoder=None) -> dict:
    chunks = read_chunks(chunks_path)
    semantic, meta = open_index(chunks_path, index_dir, encoder=encoder)
    lexical = BM25Index(chunks)
    hybrid = HybridIndex(lexical, semantic, bm25_weight=bm25_weight, candidate_k=candidate_k)
    records = [json.loads(line) for line in benchmark_path.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    results = {}
    for name, index in (("bm25", lexical), ("semantic", semantic), ("hybrid", hybrid)):
        predictions, metrics = evaluate(index, records, top_k=top_k, distinct_pages=distinct_pages)
        results[name] = {"predictions": predictions, "metrics": metrics}
    ids = [r["id"] for r in records if r["split"] == "dev"]
    stats = {name: {r["id"]: r for r in value["metrics"]["per_question"]}
             for name, value in results.items()}
    per_question = [
        {"id": qid, "task_type": stats["bm25"][qid]["type"],
         "gold_pages": stats["bm25"][qid].get("gold_pages", []),
         **{name: {"source_recall": stats[name][qid]["source_recall"],
                   "page_recall": stats[name][qid]["page_recall"],
                   "found_pages": stats[name][qid].get("found_pages", [])}
            for name in results}}
        for qid in ids
    ]
    return {"split": "dev", "chunk_count": len(chunks), "model": meta["model_name"],
            "top_k": top_k, "bm25_weight": bm25_weight, "candidate_k": candidate_k,
            "distinct_pages": distinct_pages, "methods": results,
            "per_question": per_question,
            "note": "DEV only. Page-level retrieval recall is not exact evidence quote recall or answer quality."}


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare BM25, E5 and RRF on dev questions")
    parser.add_argument("--chunks", type=Path, default=Path("data/chunks/word_safe/chunks.jsonl"))
    parser.add_argument("--index-dir", type=Path, default=Path("data/index/e5_small_v2_word_safe"))
    parser.add_argument("--benchmark", type=Path, default=Path("evaluation/benchmark_v1.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/evaluation/hybrid_dev"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--bm25-weight", type=float, default=0.75)
    parser.add_argument("--candidate-k", type=int, default=40)
    parser.add_argument("--distinct-pages", action="store_true")
    args = parser.parse_args()
    try:
        result = compare(args.chunks, args.index_dir, args.benchmark,
                         top_k=args.top_k, bm25_weight=args.bm25_weight,
                         candidate_k=args.candidate_k, distinct_pages=args.distinct_pages)
    except (OSError, SearchError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "metrics_dev.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, val in result["methods"].items():
        (args.out_dir / f"predictions_{name}_dev.jsonl").write_text(
            "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in val["predictions"]),
            encoding="utf-8")
    print(f"DEV only | {result['chunk_count']} chunks | Top-{result['top_k']} | RRF(BM25={args.bm25_weight})")
    print("Method      Source Recall@5  Evidence Page Recall@5")
    for name, val in result["methods"].items():
        summary = val["metrics"]
        print(f"{name:11s} {summary['mean_source_recall']:14.3f} {summary['mean_direct_page_recall']:22.3f}")
    print("\nPer-question page recall:")
    for q in result["per_question"]:
        if q["bm25"]["page_recall"] is not None:
            print(f"{q['id']}: BM25={q['bm25']['page_recall']:.2f}, "
                  f"E5={q['semantic']['page_recall']:.2f}, RRF={q['hybrid']['page_recall']:.2f}")
    q13 = next((q for q in result["per_question"] if q["id"] == "Q13"), None)
    if q13:
        print("\nQ13 gold:", q13["gold_pages"])
        for name in result["methods"]:
            print(f"Q13 {name} hit:", q13[name]["found_pages"])
    print(f"\nOutput: {args.out_dir}")


if __name__ == "__main__":
    main()
