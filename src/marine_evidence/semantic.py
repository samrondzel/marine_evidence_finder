"""Model-aware dense retrieval on exactly the same PDF chunks as BM25.

E5 uses *asymmetric* prefixes, but GTE ModernBERT uses unprefixed text.
The index is a (small) NumPy matrix of unit-length embeddings. Its metadata
contains a SHA-256 digest of chunks.jsonl to prevent stale-index comparisons.

No benchmark answers enter the index. Evidence text and offsets are untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import numpy as np

from marine_evidence.bm25 import SearchError, read_chunks

DEFAULT_MODEL = "intfloat/e5-small-v2"
GTE_MODEL = "Alibaba-NLP/gte-modernbert-base"


def encoding_profile(model_name: str) -> tuple[str, str]:
    """Return passage/query prefixes; E5 legacy is preserved for old indices.

    The GTE model card uses *unprefixed* text. Never feed it E5 prompts.
    Unknown model names retain legacy behaviour to avoid breaking injected
    test encoders; only E5 and GTE are supported for real comparisons.
    """
    if model_name == GTE_MODEL:
        return "", ""
    return "passage: ", "query: "

SOFT_WRAP = re.compile(r"(?<=[a-zA-Z])-[ \t]*\r?\n[ \t]*(?=[a-zA-Z])")


def search_text(text: str) -> str:
    """Repair probable PDF word-wrap for *encoding only*, not citation text."""
    return " ".join(SOFT_WRAP.sub("", text).split())


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise SearchError(f"Unable to read chunks for checksum: {path}: {exc}") from exc


def load_model(model_name: str = DEFAULT_MODEL):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise SearchError(
            "Missing dependency: run `python -m pip install -e '.[semantic,dev]'` "
            "(PowerShell: use double quotes for the extra string)."
        ) from exc
    try:
        # Downloads public model weights on first use; CPU works without a GPU.
        return SentenceTransformer(model_name, device="cpu", trust_remote_code=False)
    except Exception as exc:
        raise SearchError(f"Could not load embedding model {model_name!r}: {exc}") from exc


def _encode(encoder: Any, strings: list[str], batch_size: int) -> np.ndarray:
    """Encoder is dependency-injected so ranking and storage can be unit-tested offline."""
    if batch_size < 1:
        raise SearchError("batch_size must be positive")
    try:
        vectors = encoder.encode(
            strings, batch_size=batch_size, convert_to_numpy=True,
            normalize_embeddings=True, show_progress_bar=False,
        )
    except Exception as exc:
        raise SearchError(f"Embedding failed: {exc}") from exc
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[0] != len(strings) or arr.shape[1] < 1:
        raise SearchError(f"Embeddings have invalid shape: {arr.shape}; expected ({len(strings)}, dimensions)")
    if not np.all(np.isfinite(arr)):
        raise SearchError("Embeddings contain NaN/Inf")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    if np.any(norms <= 1e-8):
        raise SearchError("Embedding contains zero-length vector")
    return np.ascontiguousarray(arr / norms, dtype=np.float32)


def _length_warning(encoder: Any, texts: list[str]) -> dict[str, int | None]:
    """Count truncated inputs for real SentenceTransformer; no need for fake test encoders."""
    tokenizer = getattr(encoder, "tokenizer", None)
    limit = getattr(encoder, "max_seq_length", None)
    if tokenizer is None or not isinstance(limit, int) or limit <= 0:
        return {"max_model_tokens": None, "inputs_over_token_limit": 0}
    count = 0
    for text in texts:
        # SentenceTransformer's E5 encoder will truncate above this limit.
        n = len(tokenizer.encode(text, add_special_tokens=True, truncation=False))
        if n > limit:
            count += 1
    return {"max_model_tokens": limit, "inputs_over_token_limit": count}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temp = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", newline="\n",
                                         suffix=".tmp", delete=False) as file:
            temp = Path(file.name)
            json.dump(value, file, indent=2, ensure_ascii=False)
            file.write("\n")
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _atomic_npy(path: Path, vectors: np.ndarray) -> None:
    temp = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, suffix=".tmp", delete=False) as file:
            temp = Path(file.name)
            np.save(file, vectors, allow_pickle=False)
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def build_index(chunks_path: Path, index_dir: Path, *, model_name: str = DEFAULT_MODEL,
                batch_size: int = 16, encoder: Any = None) -> dict[str, Any]:
    chunks = read_chunks(chunks_path)
    if not model_name or not isinstance(model_name, str):
        raise SearchError("Invalid model name")
    model = encoder if encoder is not None else load_model(model_name)
    document_prefix, query_prefix = encoding_profile(model_name)
    passages = [document_prefix + search_text(c["text"]) for c in chunks]
    length_info = _length_warning(model, passages)
    vectors = _encode(model, passages, batch_size)
    metadata = {
        "schema_version": 1,
        "model_name": model_name,
        "embedding_dimension": int(vectors.shape[1]),
        "chunk_count": len(chunks),
        "chunk_sha256": _digest(chunks_path),
        "chunk_ids": [c["chunk_id"] for c in chunks],
        "normalization": "unit L2; cosine implemented as dot product",
        "document_prefix": document_prefix,
        "query_prefix": query_prefix,
        "pdf_soft_wraps_normalized_for_embedding_only": True,
        **length_info,
    }
    index_dir.mkdir(parents=True, exist_ok=True)
    _atomic_npy(index_dir / "vectors.npy", vectors)
    # Write metadata last. Loading fails closed if the old metadata and new vectors differ.
    _atomic_json(index_dir / "metadata.json", metadata)
    return metadata


class SemanticIndex:
    def __init__(self, chunks: list[dict[str, Any]], vectors: np.ndarray, encoder: Any,
                 *, query_prefix: str = "query: "):
        if vectors.ndim != 2 or vectors.shape[0] != len(chunks) or vectors.shape[1] < 1:
            raise SearchError("Vector count/dimension does not match chunks")
        if not np.all(np.isfinite(vectors)):
            raise SearchError("Nonfinite stored embeddings")
        norms = np.linalg.norm(vectors, axis=1)
        if not np.allclose(norms, 1, atol=2e-3):
            raise SearchError("Stored embeddings are not L2-normalized")
        self.chunks = chunks
        self.vectors = vectors
        self.encoder = encoder
        self.query_prefix = query_prefix

    def search(self, question: str, *, top_k: int = 5,
               distinct_pages: bool = False) -> list[dict[str, Any]]:
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
            raise SearchError("top_k must be a positive integer")
        if not isinstance(question, str) or not question.strip():
            return []
        query_vector = _encode(self.encoder, [self.query_prefix + search_text(question)], 1)
        if query_vector.shape[1] != self.vectors.shape[1]:
            raise SearchError("Query embedding dimension does not match index")
        scores = self.vectors @ query_vector[0]
        order = sorted(range(len(scores)), key=lambda idx: (-float(scores[idx]), self.chunks[idx]["chunk_id"]))
        chosen = []
        visited_pages = set()
        for idx in order:
            chunk = self.chunks[idx]
            page_key = (chunk["source_id"], chunk["pdf_page"])
            if distinct_pages and page_key in visited_pages:
                continue
            visited_pages.add(page_key)
            chosen.append({
                "rank": len(chosen) + 1,
                "score": round(float(scores[idx]), 6),
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


def open_index(chunks_path: Path, index_dir: Path, *, encoder: Any = None) -> tuple[SemanticIndex, dict[str, Any]]:
    try:
        meta = json.loads((index_dir / "metadata.json").read_text(encoding="utf-8"))
        # Never enable pickle when opening an untrusted array file.
        vectors = np.load(index_dir / "vectors.npy", allow_pickle=False)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SearchError(f"Cannot read dense index at {index_dir}: {exc}") from exc
    chunks = read_chunks(chunks_path)
    if meta.get("schema_version") != 1:
        raise SearchError("Unsupported index version: rebuild the index")
    if meta.get("chunk_sha256") != _digest(chunks_path):
        raise SearchError("STALE INDEX: chunks.jsonl changed. Rebuild the semantic index")
    if meta.get("chunk_ids") != [c["chunk_id"] for c in chunks]:
        raise SearchError("Index chunk IDs do not match the supplied chunks")
    if meta.get("chunk_count") != len(chunks) or meta.get("embedding_dimension") != (vectors.shape[1] if vectors.ndim==2 else None):
        raise SearchError("Index metadata dimensions do not match vectors")
    if not isinstance(meta.get("model_name"), str) or not meta["model_name"]:
        raise SearchError("Index missing embedding model identity")
    expected_doc_prefix, expected_query_prefix = encoding_profile(meta["model_name"])
    if (meta.get("document_prefix", expected_doc_prefix) != expected_doc_prefix
            or meta.get("query_prefix", expected_query_prefix) != expected_query_prefix):
        raise SearchError("Index encoding profile is incompatible with the model; rebuild the index")
    model = encoder if encoder is not None else load_model(meta["model_name"])
    return SemanticIndex(chunks, vectors, model, query_prefix=expected_query_prefix), meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Local E5 or GTE ModernBERT semantic retrieval for Marine Evidence Finder")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="Encode and persist document embeddings")
    b.add_argument("--chunks", type=Path, default=Path("data/chunks/word_safe/chunks.jsonl"))
    b.add_argument("--index-dir", type=Path, default=Path("data/index/e5_small_v2_word_safe"))
    b.add_argument("--model", default=DEFAULT_MODEL)
    b.add_argument("--batch-size", type=int, default=None)
    s = sub.add_parser("search", help="Search with a previously built dense index")
    s.add_argument("--chunks", type=Path, default=Path("data/chunks/word_safe/chunks.jsonl"))
    s.add_argument("--index-dir", type=Path, default=Path("data/index/e5_small_v2_word_safe"))
    s.add_argument("--query", required=True)
    s.add_argument("--top-k", type=int, default=5)
    s.add_argument("--distinct-pages", action="store_true")
    s.add_argument("--preview-chars", type=int, default=350)
    args = parser.parse_args()
    try:
        if args.command == "build":
            batch_size = args.batch_size if args.batch_size is not None else (4 if args.model == GTE_MODEL else 16)
            meta = build_index(args.chunks, args.index_dir, model_name=args.model, batch_size=batch_size)
            print(f"Indexed {meta['chunk_count']} chunks, {meta['embedding_dimension']} dimensions ({meta['model_name']})")
            print(f"Index: {args.index_dir}; sha256: {meta['chunk_sha256'][:12]}...")
            n = meta["inputs_over_token_limit"]
            if n:
                print(f"WARNING: {n} passages exceed the model token limit ({meta['max_model_tokens']}); model truncates them.")
        else:
            index, meta = open_index(args.chunks, args.index_dir)
            hits = index.search(args.query, top_k=args.top_k, distinct_pages=args.distinct_pages)
            print(f"Semantic search | {meta['model_name']} | {len(index.chunks)} chunks")
            print(f"Question: {args.query}\n")
            for hit in hits:
                excerpt = " ".join(hit["text"].split())[:args.preview_chars]
                print(f"#{hit['rank']} cosine={hit['score']:.4f} | {hit['source_id']} p.{hit['pdf_page']} | {hit['title']}")
                print(f"   {hit['chunk_id']} | {hit['doi']}")
                print(f"   {excerpt}\n")
            if not hits:
                print("No matches")
    except (SearchError, OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
