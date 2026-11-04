"""Dependency-free BM25 retrieval on evidence-preserving PDF chunks.

Only consumes chunks.jsonl and question strings. No evaluation labels are read.
Citation references are preserved from source chunks; token normalization is
used for searching only and does not modify the saved source text.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re
import unicodedata
from typing import Any


class SearchError(ValueError):
    """Unreadable index data or invalid search configuration."""


_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_SOFT_WRAP = re.compile(r"(?<=[a-zA-Z])-[ \t]*\n[ \t]*(?=[a-zA-Z])")


def tokenize(text: str) -> list[str]:
    """Case-insensitive simple tokenization, repairing PDF hyphenation for search.

    E.g. 'adja-\\ncent' -> 'adjacent'. A normal hyphen like vessel-noise is
    treated as a word separator. Source text is never rewritten.
    """
    if not isinstance(text, str):
        raise SearchError("search input must be text")
    text = _SOFT_WRAP.sub("", unicodedata.normalize("NFKC", text).lower())
    return _TOKEN_RE.findall(text)


def read_chunks(path: Path) -> list[dict[str, Any]]:
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SearchError(f"Could not read chunks: {path} ({exc})") from exc
    chunks = []
    seen = set()
    required = ("chunk_id", "source_id", "pdf_page", "title", "filename", "text")
    for line_no, line in enumerate(raw_lines, 1):
        if not line.strip():
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SearchError(f"Invalid JSON at line {line_no}") from exc
        if not isinstance(chunk, dict) or any(key not in chunk for key in required):
            raise SearchError(f"Missing chunk fields at line {line_no}")
        if (not isinstance(chunk["chunk_id"], str) or not chunk["chunk_id"]
                or chunk["chunk_id"] in seen):
            raise SearchError(f"Invalid/duplicate chunk id at line {line_no}")
        if (not isinstance(chunk["pdf_page"], int) or isinstance(chunk["pdf_page"], bool)
                or chunk["pdf_page"] < 1 or not isinstance(chunk["text"], str)
                or not chunk["text"].strip()):
            raise SearchError(f"Invalid page number or text at line {line_no}")
        seen.add(chunk["chunk_id"])
        chunks.append(chunk)
    if not chunks:
        raise SearchError("No chunks to index")
    return chunks


class BM25Index:
    """Classic Okapi BM25 with default k1=1.5 and b=0.75.

    Uses the Robertson-Sparck Jones +1 IDF form to avoid negative IDFs.
    Returned rankings are deterministic under score ties.
    """
    def __init__(self, chunks: list[dict[str, Any]], *, k1: float = 1.5, b: float = 0.75):
        if not 0 < k1 <= 10 or not 0 <= b <= 1:
            raise SearchError("Require 0 < k1 <= 10 and 0 <= b <= 1")
        if not chunks:
            raise SearchError("Empty chunks")
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        lengths = []
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for doc_id, chunk in enumerate(chunks):
            tokens = tokenize(chunk["text"])
            lengths.append(len(tokens))
            for term, freq in Counter(tokens).items():
                self.postings[term].append((doc_id, freq))
        self.doc_lengths = lengths
        self.n_docs = len(chunks)
        self.avgdl = sum(lengths) / len(lengths)
        if self.avgdl <= 0:
            raise SearchError("Corpus has no searchable words")
        self.idf = {
            term: math.log1p((self.n_docs - len(docs) + 0.5) / (len(docs) + 0.5))
            for term, docs in self.postings.items()
        }

    def search(self, question: str, *, top_k: int = 5,
               distinct_pages: bool = False) -> list[dict[str, Any]]:
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
            raise SearchError("top_k must be a positive integer")
        terms = set(tokenize(question))
        if not terms:
            return []
        scores: dict[int, float] = defaultdict(float)
        for term in terms:
            for doc_id, tf in self.postings.get(term, []):
                length_norm = self.k1 * (1 - self.b + self.b * self.doc_lengths[doc_id] / self.avgdl)
                scores[doc_id] += self.idf[term] * tf * (self.k1 + 1) / (tf + length_norm)
        order = sorted(scores, key=lambda idx: (-scores[idx], self.chunks[idx]["chunk_id"]))
        chosen = []
        seen_pages = set()
        for idx in order:
            chunk = self.chunks[idx]
            page = (chunk["source_id"], chunk["pdf_page"])
            if distinct_pages and page in seen_pages:
                continue
            seen_pages.add(page)
            chosen.append({
                "rank": len(chosen) + 1,
                "score": round(scores[idx], 6),
                "chunk_id": chunk["chunk_id"],
                "source_id": chunk["source_id"],
                "pdf_page": chunk["pdf_page"],
                "title": chunk["title"],
                "filename": chunk["filename"],
                "doi": chunk.get("doi", ""),
                "text": chunk["text"],
            })
            if len(chosen) >= top_k:
                break
        return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description="BM25 keyword search over PDF chunks")
    parser.add_argument("--chunks", type=Path, default=Path("data/chunks/fixed/chunks.jsonl"))
    parser.add_argument("--query", required=True, help="Question to search for")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--distinct-pages", action="store_true", help="At most one chunk per PDF page")
    parser.add_argument("--preview-chars", type=int, default=420)
    args = parser.parse_args()
    try:
        index = BM25Index(read_chunks(args.chunks))
        results = index.search(args.query, top_k=args.top_k, distinct_pages=args.distinct_pages)
    except SearchError as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(f"Indexed {index.n_docs} chunks; average length {index.avgdl:.1f} tokens")
    print(f"Question: {args.query}\n")
    for item in results:
        preview = " ".join(item["text"].split())[:args.preview_chars]
        print(f"#{item['rank']} BM25={item['score']:.3f} | {item['source_id']} p.{item['pdf_page']} | {item['title']}")
        print(f"   chunk: {item['chunk_id']} | {item['doi']}")
        print(f"   {preview}{'...' if len(item['text']) > args.preview_chars else ''}\n")
    if not results:
        print("No matching chunks. BM25 is lexical and cannot match unseen synonyms.")


if __name__ == "__main__":
    main()
