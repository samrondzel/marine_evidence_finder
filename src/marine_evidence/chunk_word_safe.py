"""Lossless, page-boundary-aware text chunking for Marine Evidence Finder.

Adds a *new* entry point; existing ingestion, chunk.py and BM25 code are untouched.
Offsets always refer to the original page string from pages.jsonl.
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

# For example, adja-\\ncent is a single logical word in PDF line-wrap layout.
# A split is NOT allowed anywhere strictly inside this contiguous raw-text span.
LETTER = r"[^\W\d_]"
WRAPPED_WORD = re.compile(rf"{LETTER}+(?:-[ \t]*\r?\n[ \t]*{LETTER}+)+", re.UNICODE)
NONSPACE = re.compile(r"\S+", re.UNICODE)


def safe_cut_positions(text: str) -> list[int]:
    """Word starts and text end, with false boundaries within soft line wraps removed.

    Positions are Python Unicode char offsets in the exact input string.
    Only whitespace-delimited word starts are allowed: the chunker never alters text.
    """
    guard_intervals = [(m.start(), m.end()) for m in WRAPPED_WORD.finditer(text)]
    # PDF pages are short; a linear sweep avoids creating a per-character mask.
    positions = [0]
    guard_idx = 0
    for match in NONSPACE.finditer(text):
        pos = match.start()
        while guard_idx < len(guard_intervals) and guard_intervals[guard_idx][1] <= pos:
            guard_idx += 1
        inside_wrap = (
            guard_idx < len(guard_intervals)
            and guard_intervals[guard_idx][0] < pos < guard_intervals[guard_idx][1]
        )
        if not inside_wrap and pos != positions[-1]:
            positions.append(pos)
    if len(text) != positions[-1]:
        positions.append(len(text))
    return positions


def chunk_spans(text: str, max_chars: int = 2000, overlap_chars: int = 300) -> list[tuple[int, int]]:
    """Cover a page in overlapping [start,end) source offsets, never cutting words.

    If a single unbroken logical word exceeds max_chars, fail explicitly instead of
    silently violating the configured maximum or corrupting citation provenance.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be >= 0 and < max_chars")
    if not text:
        return []

    cuts = safe_cut_positions(text)
    result: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        if len(text) - start <= max_chars:
            end = len(text)
        else:
            # The greatest safe boundary at or before this chunk's budget.
            index = bisect.bisect_right(cuts, start + max_chars) - 1
            if index < 0 or cuts[index] <= start:
                raise ValueError(
                    f"No word-safe boundary within max_chars={max_chars} "
                    f"starting at char offset {start}; a token/URL may be too long"
                )
            end = cuts[index]
        result.append((start, end))
        if end == len(text):
            break

        # Find word boundary as close as possible to the desired overlap,
        # while strictly advancing start. Choose the nearest of two candidates.
        target = end - overlap_chars
        lo_index = bisect.bisect_right(cuts, target) - 1
        candidates: list[int] = []
        for i in (lo_index, lo_index + 1):
            if 0 <= i < len(cuts) and start < cuts[i] <= end:
                candidates.append(cuts[i])
        if candidates:
            new_start = min(candidates, key=lambda p: (abs(p - target), p))
        else:
            # Unusual case: there are no inner word boundaries.
            new_start = end
        start = new_start
    return result


def page_to_chunks(page: dict[str, Any], max_chars: int = 2000,
                   overlap_chars: int = 300) -> list[dict[str, Any]]:
    raw = page.get("text")
    if not isinstance(raw, str):
        raise ValueError("page.text must be a string")
    source_id = page.get("source_id")
    pdf_page = page.get("pdf_page")
    if not isinstance(source_id, str) or not source_id or not isinstance(pdf_page, int) or pdf_page < 1:
        raise ValueError("page must contain source_id (str) and pdf_page (positive int)")
    page_id = page.get("page_id") or f"{source_id}:p{pdf_page:04d}"
    chunks = []
    for index, (a, b) in enumerate(chunk_spans(raw, max_chars, overlap_chars), start=1):
        segment = raw[a:b]
        chunk = {
            "chunk_id": f"{page_id}:c{index:04d}",
            "page_id": page_id,
            "source_id": source_id,
            "title": page.get("title", ""),
            "doi": page.get("doi", ""),
            "filename": page.get("filename", ""),
            "pdf_page": pdf_page,
            "start_char": a,
            "end_char": b,
            "text": segment,              # DO NOT normalize: preserves citations and offsets
            "char_count": len(segment),
            "word_count": len(segment.split()),
        }
        assert raw[a:b] == chunk["text"]
        chunks.append(chunk)
    return chunks


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8-sig") as stream:
        for n, line in enumerate(stream, start=1):
            if line.strip():
                try:
                    obj = json.loads(line)
                    if not isinstance(obj, dict):
                        raise ValueError("expected JSON object")
                except (json.JSONDecodeError, ValueError) as e:
                    raise ValueError(f"{path}:{n}: {e}") from e
                yield obj


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n",
                                         dir=path.parent, suffix=".tmp", delete=False) as stream:
            tmp = Path(stream.name)
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.replace(tmp, path)
    finally:
        if tmp and tmp.exists():
            tmp.unlink()


def build(pages_path: Path, out_dir: Path, max_chars: int, overlap_chars: int) -> dict[str, Any]:
    if not pages_path.is_file():
        raise FileNotFoundError(f"pages.jsonl not found: {pages_path}")
    pages = list(read_jsonl(pages_path))
    ids = [p.get("page_id") or (p.get("source_id"), p.get("pdf_page")) for p in pages]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate page_id/source_id+page in input")
    all_chunks = []
    for p in pages:
        try:
            page_chunks = page_to_chunks(p, max_chars, overlap_chars)
        except ValueError as e:
            raise ValueError(f"{p.get('source_id')} p.{p.get('pdf_page')}: {e}") from e
        raw = p["text"]
        if raw and (not page_chunks or page_chunks[0]["start_char"] != 0 or
                    page_chunks[-1]["end_char"] != len(raw)):
            raise AssertionError("Lost page start/end")
        if any(x["end_char"] != len(raw) and y["start_char"] > x["end_char"]
               for x, y in zip(page_chunks, page_chunks[1:])):
            raise AssertionError("Gap between chunks")
        all_chunks.extend(page_chunks)
    atomic_write_jsonl(out_dir / "chunks.jsonl", all_chunks)
    stats = {
        "pages_input": len(pages),
        "chunks_output": len(all_chunks),
        "max_chars": max_chars,
        "overlap_chars": overlap_chars,
        "max_actual_chunk_chars": max((len(c["text"]) for c in all_chunks), default=0),
        "sources": dict(sorted(Counter(c["source_id"] for c in all_chunks).items())),
        "source_pages": str(pages_path),
        "chunking_version": "word-safe-v1",
        "raw_text_preserved": True,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "chunking_report.json").open("w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-chunk pages.jsonl without breaking words or PDF soft wraps")
    parser.add_argument("--pages", type=Path, default=Path("data/processed/pages.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/chunks/word_safe"))
    parser.add_argument("--max-chars", type=int, default=2000)
    parser.add_argument("--overlap-chars", type=int, default=300)
    args = parser.parse_args()
    stats = build(args.pages, args.out_dir, args.max_chars, args.overlap_chars)
    print(f"PASS: {stats['pages_input']} pages -> {stats['chunks_output']} word-safe chunks")
    print(f"max chunk: {stats['max_actual_chunk_chars']} chars; overlap target: {stats['overlap_chars']} chars")
    print(f"output: {args.out_dir / 'chunks.jsonl'}")


if __name__ == "__main__":
    main()
