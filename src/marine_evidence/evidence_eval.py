"""Quote-level retrieval evaluation against development-only annotated evidence.

Unlike page recall, credit is given only if a returned chunk literally contains
an annotated *support* quotation. Long-context matching stays source-local.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import unicodedata
from typing import Any

from .bm25 import BM25Index, read_chunks


def normalize_quote(text: str) -> str:
    """Normalize presentation whitespace without inventing missing words."""
    return " ".join(unicodedata.normalize("NFKC", text).replace("\u00ad", "").split()).casefold()


def quote_in_chunk(quote: str, chunk_text: str) -> bool:
    return bool(quote.strip()) and normalize_quote(quote) in normalize_quote(chunk_text)


def support_evidence(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in record["evidence"] if e["evidence_role"] == "support"]


def evaluate_dev(chunks: list[dict[str, Any]], rows: list[dict[str, Any]],
                 *, top_k: int = 5, distinct_pages: bool = False) -> dict[str, Any]:
    if top_k < 1:
        raise ValueError("top_k must be >=1")
    dev = [r for r in rows if r.get("split") == "dev"]
    if not dev:
        raise ValueError("No dev items found; evaluation must not use test labels")
    index = BM25Index(chunks)
    per_question: list[dict[str, Any]] = []
    for r in dev:
        if r["answerability"] != "answerable":
            per_question.append({"id": r["id"], "task_type": r["task_type"],
                                 "gold_support_quotes": 0, "quote_recall_at_k": None,
                                 "any_quote_hit": None, "note": "abstention excluded from retrieval metrics"})
            continue
        evidence = support_evidence(r)
        if not evidence:
            raise ValueError(f"No annotated support for {r['id']}")
        retrieved = index.search(r["question"], top_k=top_k,
                                 distinct_pages=distinct_pages)
        matches = []
        for e in evidence:
            gold_page = (e["source_id"], e["pdf_page"])
            matching_chunks = [c["chunk_id"] for c in chunks
                               if (c["source_id"], c["pdf_page"]) == gold_page
                               and quote_in_chunk(e["quote"], c["text"])]
            hit = next((h for h in retrieved
                        if (h["source_id"], h["pdf_page"]) == gold_page
                        and quote_in_chunk(e["quote"], h["text"])), None)
            matches.append({"source_id": e["source_id"], "pdf_page": e["pdf_page"],
                            "quote_preview": e["quote"][:120],
                            "present_in_any_chunk": bool(matching_chunks),
                            "found_in_top_k": hit is not None,
                            "rank": hit["rank"] if hit else None,
                            "hit_chunk_id": hit["chunk_id"] if hit else None})
        found_count = sum(m["found_in_top_k"] for m in matches)
        per_question.append({
            "id": r["id"], "task_type": r["task_type"], "gold_support_quotes": len(matches),
            "quotes_found": found_count,
            "quote_recall_at_k": found_count / len(matches),
            "any_quote_hit": found_count > 0,
            "chunk_oracle_coverage": sum(m["present_in_any_chunk"] for m in matches) / len(matches),
            "evidence_matches": matches,
            "top_chunk_ids": [h["chunk_id"] for h in retrieved],
        })
    answerable = [q for q in per_question if q["quote_recall_at_k"] is not None]
    all_quotes = [m for q in answerable for m in q["evidence_matches"]]
    result = {
        "split": "dev", "retriever": "BM25", "top_k": top_k,
        "distinct_pages": distinct_pages, "question_count": len(dev),
        "answerable_count": len(answerable),
        "support_quotes": len(all_quotes),
        "quotes_found_in_top_k": sum(m["found_in_top_k"] for m in all_quotes),
        "micro_quote_recall": sum(m["found_in_top_k"] for m in all_quotes) / len(all_quotes),
        "macro_quote_recall": statistics.mean(q["quote_recall_at_k"] for q in answerable),
        "any_quote_hit_rate": statistics.mean(q["any_quote_hit"] for q in answerable),
        "oracle_quote_coverage": statistics.mean(m["present_in_any_chunk"] for m in all_quotes),
        "per_question": per_question,
        "caveat": "Exact normalized supporting quote substring in retrieved chunk. Does NOT grade semantic relevance, evidence sufficiency, faithfulness, or unsupported-question abstention.",
    }
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="BM25 exact evidence quote retrieval, DEV only")
    p.add_argument("--chunks", type=Path, default=Path("data/chunks/word_safe/chunks.jsonl"))
    p.add_argument("--benchmark", type=Path, default=Path("evaluation/benchmark_v1.jsonl"))
    p.add_argument("--out-dir", type=Path, default=Path("data/evaluation/evidence_dev"))
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--distinct-pages", action="store_true")
    args = p.parse_args()
    try:
        chunks = read_chunks(args.chunks)
        rows = [json.loads(s) for s in args.benchmark.read_text(encoding="utf-8").splitlines() if s.strip()]
        report = evaluate_dev(chunks, rows, top_k=args.top_k, distinct_pages=args.distinct_pages)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "metrics_dev.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        p.exit(1, f"ERROR: {exc}\n")
    print(f"DEV only | {len(chunks)} chunks | {report['answerable_count']} answerable questions | top-{args.top_k}")
    print(f"Quote recall (micro): {report['micro_quote_recall']:.3f} ({report['quotes_found_in_top_k']}/{report['support_quotes']})")
    print(f"Quote recall (macro): {report['macro_quote_recall']:.3f}")
    print(f"Any support quote in top-{args.top_k}: {report['any_quote_hit_rate']:.3f}")
    print(f"Quote coverage across all chunks (oracle): {report['oracle_quote_coverage']:.3f}")
    for q in report["per_question"]:
        if q["quote_recall_at_k"] is not None:
            print(f"  {q['id']}: {q['quotes_found']}/{q['gold_support_quotes']} quotes, recall={q['quote_recall_at_k']:.2f}")
    print(f"Report: {args.out_dir / 'metrics_dev.json'}")


if __name__ == "__main__":
    main()
