"""DEV-only head-to-head: BM25 vs E5-small-v2 vs GTE-ModernBERT.

The same chunks.jsonl and the same gold questions are used for every retriever.
The held-out test labels are never scored or reported by this script.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics

from marine_evidence.bm25 import BM25Index, read_chunks, SearchError
from marine_evidence.semantic import GTE_MODEL, open_index
from scripts.eval_bm25_dev import evaluate


def compare(chunks_path: Path, e5_dir: Path, gte_dir: Path, benchmark_path: Path, *,
            top_k: int = 5, distinct_pages: bool = False,
            e5_encoder=None, gte_encoder=None) -> dict:
    if e5_dir.resolve() == gte_dir.resolve():
        raise SearchError("E5 and GTE index directories must be different")
    chunks = read_chunks(chunks_path)
    e5, e5_meta = open_index(chunks_path, e5_dir, encoder=e5_encoder)
    gte, gte_meta = open_index(chunks_path, gte_dir, encoder=gte_encoder)
    if e5_meta["model_name"] != "intfloat/e5-small-v2":
        raise SearchError("--e5-index is not an intfloat/e5-small-v2 index")
    if gte_meta["model_name"] != GTE_MODEL:
        raise SearchError("--gte-index is not a GTE ModernBERT index")
    rows = [json.loads(s) for s in benchmark_path.read_text(encoding="utf-8").splitlines() if s.strip()]
    records = [r for r in rows if r["split"] == "dev"]
    if not records:
        raise SearchError("Benchmark contains no dev questions")
    indices = {"bm25": BM25Index(chunks), "e5": e5, "gte": gte}
    scores = {}
    for name, index in indices.items():
        predictions, metrics = evaluate(index, records, top_k=top_k, distinct_pages=distinct_pages)
        scores[name] = {"predictions": predictions, "metrics": metrics}
    by_id = {name: {x["id"]: x for x in d["metrics"]["per_question"]}
             for name, d in scores.items()}
    # Existing evaluator includes method pages alongside direct support pages.
    # Report that legacy metric unchanged for historical comparability, but
    # additionally report retrieval of pages with role == 'support' only.
    direct_support = {r["id"]: {(e["source_id"], int(e["pdf_page"]))
                                for e in r.get("evidence", []) if e.get("evidence_role") == "support"}
                      for r in records if r.get("answerability") == "answerable"}
    support_per_method = {name: {} for name in indices}
    for name in indices:
        for pred in scores[name]["predictions"]:
            qid = pred["id"]
            if qid in direct_support:
                gold = direct_support[qid]
                if not gold:
                    raise SearchError(f"No 'support' gold evidence for {qid}")
                found = {(x["source_id"], int(x["pdf_page"])) for x in pred["retrieved"]}
                support_per_method[name][qid] = len(found & gold) / len(gold)
        scores[name]["support_only_page_recall"] = statistics.mean(support_per_method[name].values())
    per_question = []
    for q in records:
        qid = q["id"]
        first = by_id["bm25"][qid]
        per_question.append({
            "id": qid, "task_type": first["type"],
            "gold_pages": first.get("gold_pages", []),
            **{name: {"source_recall": by_id[name][qid]["source_recall"],
                      "page_recall": by_id[name][qid]["page_recall"],
                      "found_pages": by_id[name][qid].get("found_pages", []),
                      "support_only_page_recall": support_per_method[name].get(qid)}
               for name in indices},
        })
    q13 = next((r for r in records if r["id"] == "Q13" and r["answerability"] == "answerable"), None)
    q13_extra = None
    if q13:
        gold_pages = sorted({(x["source_id"], int(x["pdf_page"]))
                             for x in q13.get("evidence", []) if x.get("evidence_role") not in ("scope", "limitation")})
        q13_extra = {
            "gold_pages_and_roles": [
                {"page": f"{e['source_id']}:p{e['pdf_page']}", "role": e["evidence_role"]}
                for e in q13["evidence"] if e["evidence_role"] not in ("scope", "limitation")
            ]
        }
        for name, index in indices.items():
            deeper = index.search(q13["question"], top_k=min(len(chunks), 30), distinct_pages=False)
            q13_extra[name] = {f"{s}:p{p}": next((x["rank"] for x in deeper
                                                    if x["source_id"] == s and x["pdf_page"] == p), None)
                               for s, p in gold_pages}
    return {
        "split": "dev", "top_k": top_k, "chunk_count": len(chunks),
        "model_e5": e5_meta["model_name"], "model_gte": gte_meta["model_name"],
        "e5_inputs_over_token_limit": e5_meta.get("inputs_over_token_limit"),
        "gte_inputs_over_token_limit": gte_meta.get("inputs_over_token_limit"),
        "distinct_pages": distinct_pages, "methods": scores,
        "per_question": per_question, "q13_rank_diagnostic_top30": q13_extra,
        "note": "DEV only; page recall is not quote recall, citation validity, or generation quality.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fair DEV BM25 vs E5 vs GTE comparison on identical chunks")
    parser.add_argument("--chunks", type=Path, default=Path("data/chunks/word_safe/chunks.jsonl"))
    parser.add_argument("--e5-index", type=Path, default=Path("data/index/e5_small_v2_word_safe"))
    parser.add_argument("--gte-index", type=Path, default=Path("data/index/gte_modernbert_word_safe"))
    parser.add_argument("--benchmark", type=Path, default=Path("evaluation/benchmark_v1.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/evaluation/compare_dev_gte"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--distinct-pages", action="store_true")
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be positive")
    try:
        report = compare(args.chunks, args.e5_index, args.gte_index, args.benchmark,
                         top_k=args.top_k, distinct_pages=args.distinct_pages)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "metrics_dev.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        for name, r in report["methods"].items():
            (args.out_dir / f"predictions_{name}_dev.jsonl").write_text(
                "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in r["predictions"]), encoding="utf-8")
    except (OSError, SearchError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(f"DEV only | {report['chunk_count']} identical chunks | top-{report['top_k']}")
    print("Method      SourceRecall  LegacyPageRecall  SupportOnlyPageRecall")
    for name, item in report["methods"].items():
        m = item["metrics"]
        print(f"{name:11s} {m['mean_source_recall']:12.3f} "
              f"{m['mean_direct_page_recall']:17.3f} "
              f"{item['support_only_page_recall']:22.3f}")
    print("\nPer-question legacy/support-only page recall:")
    for q in report["per_question"]:
        if q["bm25"]["page_recall"] is not None:
            print(f"  {q['id']}: " + " | ".join(
                f"{name}={q[name]['page_recall']:.2f}/{q[name]['support_only_page_recall']:.2f}"
                for name in ("bm25", "e5", "gte")))
    if report["q13_rank_diagnostic_top30"] is not None:
        print("\nQ13 gold page roles:", report["q13_rank_diagnostic_top30"]["gold_pages_and_roles"])
        print("Q13: rank of gold pages among top-30 chunks (None = absent):")
        for name, ranks in report["q13_rank_diagnostic_top30"].items():
            if name != "gold_pages_and_roles":
                print(f"  {name}: {ranks}")
    print(f"\nSaved DEV-only results to {args.out_dir}")


if __name__ == "__main__":
    main()
