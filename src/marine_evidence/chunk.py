"""Deterministic, citation-safe chunking of page-level PDF text.

Chunks never cross page boundaries and store exact character offsets into the
original `pages.jsonl` text. Only source papers are indexed; no benchmark data
is opened by this module.

Run: python -m marine_evidence.chunk --pages data/processed/pages.jsonl \\
     --out-dir data/chunks/fixed --max-chars 1800 --overlap-chars 300
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any


class ChunkingError(Exception):
    """Bad chunking configuration or malformed page-level input."""


def validate_config(max_chars: int, overlap_chars: int, strategy: str) -> None:
    if strategy not in ("fixed", "boundary"):
        raise ChunkingError("strategy must be 'fixed' or 'boundary'")
    if not isinstance(max_chars, int) or max_chars < 200:
        raise ChunkingError("max_chars must be at least 200")
    if not isinstance(overlap_chars, int) or overlap_chars < 0 or overlap_chars >= max_chars:
        raise ChunkingError("overlap_chars must satisfy 0 <= overlap_chars < max_chars")
    # Avoid almost-zero progress from huge overlap.
    if max_chars - overlap_chars < 100:
        raise ChunkingError("max_chars - overlap_chars must be at least 100")


def _select_end(text: str, start: int, max_chars: int, strategy: str) -> int:
    """Choose a boundary without rewriting the extracted source text."""
    limit = min(start + max_chars, len(text))
    if limit == len(text):
        return limit

    floor = start + int(max_chars * 0.65)
    if strategy == "boundary":
        # Blank line, then sentence boundary. PDF line-breaks are often mere wraps;
        # do not treat every newline as a true paragraph.
        for token in ("\n\n", ". ", ".\n", "? ", "! "):
            pos = text.rfind(token, floor, limit)
            if pos >= floor:
                return pos + len(token)
    # A word-friendly split is the fallback for both strategies.
    cut_candidates = [text.rfind(c, floor, limit) for c in (" ", "\n", "\t")]
    cut = max(cut_candidates)
    if cut >= floor:
        return cut + 1
    return limit


def _select_next_start(text: str, start: int, end: int, overlap_chars: int) -> int:
    if overlap_chars == 0:
        return end
    raw = max(start + 1, end - overlap_chars)
    # Move the start slightly backwards to the beginning of the word.
    prev = max(text.rfind(" ", start + 1, raw), text.rfind("\n", start + 1, raw))
    if prev > start and raw - prev <= 50:
        return prev + 1
    return raw


def chunk_page(page: dict[str, Any], *, max_chars: int = 1800,
               overlap_chars: int = 300, strategy: str = "fixed") -> list[dict[str, Any]]:
    validate_config(max_chars, overlap_chars, strategy)
    required = ("page_id", "source_id", "filename", "title", "doi", "pdf_page", "text", "char_count")
    if any(key not in page for key in required):
        raise ChunkingError(f"Missing page fields for {page.get('page_id', '<unknown>')}")
    if not isinstance(page["text"], str) or page["char_count"] != len(page["text"]):
        raise ChunkingError(f"Invalid text or char_count for {page['page_id']}")
    if not isinstance(page["pdf_page"], int) or page["pdf_page"] < 1:
        raise ChunkingError(f"Invalid pdf_page for {page['page_id']}")
    text = page["text"]
    if not text:
        return []
    out = []
    start = 0
    while start < len(text):
        end = _select_end(text, start, max_chars, strategy)
        if end <= start or end - start > max_chars:
            raise ChunkingError(f"Invalid chunk boundary for {page['page_id']}")
        identifier = f"{page['page_id']}:{strategy}:{max_chars}:{overlap_chars}:{start}:{end}"
        fragment = text[start:end]
        out.append({
            "chunk_id": f"{page['page_id']}:c{len(out)+1:03d}-{hashlib.sha256(identifier.encode()).hexdigest()[:10]}",
            "page_id": page["page_id"],
            "source_id": page["source_id"],
            "filename": page["filename"],
            "title": page["title"],
            "doi": page["doi"],
            "pdf_page": page["pdf_page"],
            "start_char": start,
            "end_char": end,
            "text": fragment,
            "char_count": len(fragment),
            "word_count": len(re.findall(r"\S+", fragment)),
        })
        if end == len(text):
            break
        next_start = _select_next_start(text, start, end, overlap_chars)
        if not start < next_start <= end:
            raise ChunkingError(f"Chunker made no progress at {page['page_id']}")
        start = next_start
    return out


def build_chunks(pages_path: Path, out_dir: Path, *, max_chars: int = 1800,
                 overlap_chars: int = 300, strategy: str = "fixed") -> dict[str, Any]:
    validate_config(max_chars, overlap_chars, strategy)
    try:
        lines = pages_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ChunkingError(f"Cannot read {pages_path}: {exc}") from exc
    if not lines:
        raise ChunkingError("No input pages")

    records: list[dict[str, Any]] = []
    unique_pages = set()
    by_source = Counter()
    empty_pages = []
    for number, line in enumerate(lines, 1):
        try:
            page = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ChunkingError(f"Bad JSON on line {number}") from exc
        if not isinstance(page, dict):
            raise ChunkingError(f"Expected JSON object on line {number}")
        pid = page.get("page_id")
        if not isinstance(pid, str) or pid in unique_pages:
            raise ChunkingError(f"Missing or duplicate page_id: {pid!r}")
        unique_pages.add(pid)
        local = chunk_page(page, max_chars=max_chars, overlap_chars=overlap_chars, strategy=strategy)
        if not local:
            empty_pages.append(pid)
        records.extend(local)
        by_source[page["source_id"]] += len(local)

    if not records:
        raise ChunkingError("No chunks generated")
    report = {
        "strategy": strategy, "max_chars": max_chars, "overlap_chars": overlap_chars,
        "pages": len(unique_pages), "chunks": len(records),
        "empty_pages": empty_pages, "chunks_by_source": dict(sorted(by_source.items())),
        "min_chunk_chars": min(r["char_count"] for r in records),
        "max_chunk_chars": max(r["char_count"] for r in records),
        "note": "Character sizes are NOT tokens. Exact source offsets and 1-based PDF pages are preserved.",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks_target = out_dir / "chunks.jsonl"
    report_target = out_dir / "chunking_report.json"
    chunks_temp = out_dir / "chunks.jsonl.tmp"
    report_temp = out_dir / "chunking_report.json.tmp"
    try:
        with chunks_temp.open("w", encoding="utf-8", newline="\n") as dest:
            for record in records:
                dest.write(json.dumps(record, ensure_ascii=False) + "\n")
        report_temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        chunks_temp.replace(chunks_target)
        report_temp.replace(report_target)
    finally:
        chunks_temp.unlink(missing_ok=True)
        report_temp.unlink(missing_ok=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build provenance-preserving search chunks")
    parser.add_argument("--pages", type=Path, default=Path("data/processed/pages.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/chunks/fixed"))
    parser.add_argument("--max-chars", type=int, default=1800)
    parser.add_argument("--overlap-chars", type=int, default=300)
    parser.add_argument("--strategy", choices=["fixed", "boundary"], default="fixed")
    args = parser.parse_args()
    try:
        r = build_chunks(args.pages, args.out_dir, max_chars=args.max_chars,
                         overlap_chars=args.overlap_chars, strategy=args.strategy)
    except ChunkingError as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(f"PASS: {r['pages']} pages -> {r['chunks']} chunks "
          f"({r['strategy']}, max {r['max_chars']} chars, overlap {r['overlap_chars']} chars)")
    print(f"Output: {args.out_dir / 'chunks.jsonl'}")


if __name__ == "__main__":
    main()
