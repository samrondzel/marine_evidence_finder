"""Hybrid BM25 + E5 retrieval via weighted Reciprocal Rank Fusion (RRF).

Scores from BM25 and cosine are not comparable. Fuse *ranks* instead:
    score(c) = w / (rrf_k + rank_bm25(c))
             + (1 - w) / (rrf_k + rank_dense(c))
Missing items contribute zero. The lexical/dense indices must share chunk IDs.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from marine_evidence.bm25 import BM25Index, SearchError, read_chunks
from marine_evidence.semantic import open_index


class HybridIndex:
    def __init__(self, lexical: Any, semantic: Any, *, bm25_weight: float = 0.75,
                 candidate_k: int = 40, rrf_k: int = 60):
        if not 0 <= bm25_weight <= 1:
            raise SearchError("bm25_weight must be within [0, 1]")
        if not isinstance(candidate_k, int) or candidate_k < 1:
            raise SearchError("candidate_k must be positive")
        if not isinstance(rrf_k, int) or rrf_k < 1:
            raise SearchError("rrf_k must be positive")
        self.lexical = lexical
        self.semantic = semantic
        self.bm25_weight = bm25_weight
        self.candidate_k = candidate_k
        self.rrf_k = rrf_k

    def search(self, question: str, *, top_k: int = 5,
               distinct_pages: bool = False) -> list[dict[str, Any]]:
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
            raise SearchError("top_k must be a positive integer")
        if not isinstance(question, str) or not question.strip():
            return []
        # Don't truncate either source to just top-5 before combining.
        n = max(top_k, self.candidate_k)
        lex_hits = self.lexical.search(question, top_k=n, distinct_pages=False)
        sem_hits = self.semantic.search(question, top_k=n, distinct_pages=False)
        candidates: dict[str, dict[str, Any]] = {}
        for name, weight, results in (
            ("bm25", self.bm25_weight, lex_hits),
            ("semantic", 1.0 - self.bm25_weight, sem_hits),
        ):
            for rank, hit in enumerate(results, 1):
                key = hit["chunk_id"]
                if key not in candidates:
                    candidates[key] = {
                        **hit, "score": 0.0, "bm25_rank": None,
                        "semantic_rank": None,
                    }
                candidates[key]["score"] += weight / (self.rrf_k + rank)
                candidates[key][f"{name}_rank"] = rank
        ranked = sorted(candidates.values(), key=lambda h: (-h["score"], h["chunk_id"]))
        output = []
        seen_pages = set()
        for hit in ranked:
            key = (hit["source_id"], hit["pdf_page"])
            if distinct_pages and key in seen_pages:
                continue
            seen_pages.add(key)
            output.append({**hit, "score": round(hit["score"], 9), "rank": len(output) + 1})
            if len(output) == top_k:
                break
        return output


def main() -> None:
    parser = argparse.ArgumentParser(description="BM25 + E5 weighted RRF search")
    parser.add_argument("--chunks", type=Path, default=Path("data/chunks/word_safe/chunks.jsonl"))
    parser.add_argument("--index-dir", type=Path, default=Path("data/index/e5_small_v2_word_safe"))
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=40)
    parser.add_argument("--bm25-weight", type=float, default=0.75)
    parser.add_argument("--distinct-pages", action="store_true")
    args = parser.parse_args()
    try:
        chunks = read_chunks(args.chunks)
        semantic, metadata = open_index(args.chunks, args.index_dir)
        index = HybridIndex(BM25Index(chunks), semantic, bm25_weight=args.bm25_weight,
                            candidate_k=args.candidate_k)
        hits = index.search(args.query, top_k=args.top_k, distinct_pages=args.distinct_pages)
        print(f"Hybrid RRF | {len(chunks)} chunks | {metadata['model_name']} | BM25 weight {args.bm25_weight}")
        for h in hits:
            preview = " ".join(h["text"].split())[:330]
            print(f"#{h['rank']} | {h['source_id']} p.{h['pdf_page']} | BM25 rank={h['bm25_rank']} "
                  f"E5 rank={h['semantic_rank']} | RRF={h['score']:.6f}")
            print(f"    {preview}")
    except (OSError, SearchError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
