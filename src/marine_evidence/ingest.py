"""Ingest a fixed PDF corpus into one JSON record per PDF page.

Usage:
    python -m marine_evidence.ingest --papers-dir papers \
        --manifest evaluation/papers_manifest.json --out-dir data/processed

This is intentionally a baseline: PyMuPDF reading order is not guaranteed
for multi-column articles or tables. The default native order preserves more
continuous evidence spans in our dev corpus than sort=True. Inspect samples
before selecting a chunking strategy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF


class IngestionError(Exception):
    """A corpus input failed validation; do not silently index it."""


def normalize_text(text: str) -> str:
    """Normalize whitespace but retain line and paragraph boundaries.

    Avoid automatically joining end-of-line hyphens: scientific names and
    technical terms may genuinely contain hyphens.
    """
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ").replace("\x00", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for piece in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(piece)
    return digest.hexdigest()


def load_manifest(path: Path) -> list[dict[str, Any]]:
    try:
        papers = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IngestionError(f"Cannot read manifest {path}: {exc}") from exc
    if not isinstance(papers, list) or not papers:
        raise IngestionError("Manifest must be a non-empty JSON list")
    ids, filenames = set(), set()
    for paper in papers:
        if not isinstance(paper, dict):
            raise IngestionError("Every manifest item must be an object")
        required = ("id", "local_pdf_filename", "title", "doi", "sha256", "pdf_page_count")
        if any(key not in paper for key in required):
            raise IngestionError(f"Missing manifest fields in {paper!r}")
        name = paper["local_pdf_filename"]
        if not isinstance(name, str) or Path(name).name != name or not name.lower().endswith(".pdf"):
            raise IngestionError(f"Unsafe PDF filename: {name!r}")
        if paper["id"] in ids or name in filenames:
            raise IngestionError(f"Duplicate PDF id or filename: {paper['id']}, {name}")
        if not isinstance(paper["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", paper["sha256"]):
            raise IngestionError(f"Bad SHA-256 in manifest for {name}")
        if not isinstance(paper["pdf_page_count"], int) or paper["pdf_page_count"] < 1:
            raise IngestionError(f"Bad PDF page count in manifest for {name}")
        ids.add(paper["id"])
        filenames.add(name)
    return papers


def iter_paper_pages(paper: dict[str, Any], pdf_path: Path, reading_order: str = "native"):
    """Yield metadata and text for each 1-based PDF page."""
    if reading_order not in ("native", "sorted"):
        raise IngestionError(f"Unknown reading order: {reading_order}")
    if not pdf_path.is_file():
        raise IngestionError(f"Missing PDF: {pdf_path}")
    actual_hash = sha256_file(pdf_path)
    if actual_hash != paper["sha256"]:
        raise IngestionError(f"Checksum mismatch for {pdf_path.name}: expected {paper['sha256']}, got {actual_hash}")
    try:
        with fitz.open(pdf_path) as document:
            if len(document) != paper["pdf_page_count"]:
                raise IngestionError(f"Page count mismatch for {pdf_path.name}: expected {paper['pdf_page_count']}, got {len(document)}")
            for index, page in enumerate(document):
                text = normalize_text(page.get_text("text", sort=(reading_order == "sorted")))
                yield {
                    "page_id": f"{paper['id']}:p{index + 1:04d}",
                    "source_id": paper["id"],
                    "filename": paper["local_pdf_filename"],
                    "title": paper["title"],
                    "doi": paper["doi"],
                    "pdf_page": index + 1,
                    "text": text,
                    "char_count": len(text),
                }
    except (RuntimeError, ValueError) as exc:
        raise IngestionError(f"Could not extract PDF {pdf_path.name}: {exc}") from exc


def ingest(papers_dir: Path, manifest_path: Path, out_dir: Path, reading_order: str = "native") -> dict[str, Any]:
    if reading_order not in ("native", "sorted"):
        raise IngestionError(f"Unknown reading order: {reading_order}")
    papers = load_manifest(manifest_path)
    # Fail before creating output, including if a PDF was changed after gold annotation.
    for paper in papers:
        path = papers_dir / paper["local_pdf_filename"]
        if not path.is_file():
            raise IngestionError(f"Missing PDF: {path}")
        if sha256_file(path) != paper["sha256"]:
            raise IngestionError(f"Checksum mismatch for {path.name}")
    # Prepare complete output in memory: safe for this small 75-page corpus.
    records: list[dict[str, Any]] = []
    for paper in papers:
        records.extend(iter_paper_pages(paper, papers_dir / paper["local_pdf_filename"], reading_order=reading_order))

    empty = [row["page_id"] for row in records if not row["text"]]
    short = [row["page_id"] for row in records if row["char_count"] < 200]
    report = {
        "extraction_method": f"pymupdf_text_{reading_order}",
        "papers": len(papers),
        "pages": len(records),
        "characters": sum(row["char_count"] for row in records),
        "empty_pages": empty,
        "short_pages_lt_200_chars": short,
        "pages_by_source": dict(Counter(row["source_id"] for row in records)),
        "note": "PDF reading order can be incorrect in multi-column layouts; review page samples before chunking.",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    pages_file = out_dir / "pages.jsonl"
    report_file = out_dir / "ingestion_report.json"
    pages_temp = out_dir / "pages.jsonl.tmp"
    report_temp = out_dir / "ingestion_report.json.tmp"
    try:
        with pages_temp.open("w", encoding="utf-8", newline="\n") as handle:
            for row in records:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        report_temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        pages_temp.replace(pages_file)
        report_temp.replace(report_file)
    finally:
        pages_temp.unlink(missing_ok=True)
        report_temp.unlink(missing_ok=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="PDF to source-linked page JSONL")
    parser.add_argument("--papers-dir", type=Path, default=Path("papers"))
    parser.add_argument("--manifest", type=Path, default=Path("evaluation/papers_manifest.json"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--reading-order", choices=["native", "sorted"], default="native",
                        help="PyMuPDF text ordering; native was better on the dev evidence excerpts")
    args = parser.parse_args()
    try:
        report = ingest(args.papers_dir, args.manifest, args.out_dir, reading_order=args.reading_order)
    except IngestionError as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(f"PASS: {report['papers']} PDFs -> {report['pages']} pages, {report['characters']:,} characters")
    print(f"Empty pages: {len(report['empty_pages'])}; short pages: {len(report['short_pages_lt_200_chars'])}")
    print(f"Output: {args.out_dir / 'pages.jsonl'}")
    print("NEXT: inspect a multi-column sample before indexing chunks.")


if __name__ == "__main__":
    main()
