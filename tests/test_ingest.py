import hashlib
import json
from pathlib import Path

import fitz
import pytest

from marine_evidence.ingest import IngestionError, ingest, normalize_text


def sample_corpus(tmp_path: Path):
    papers = tmp_path / "papers"
    papers.mkdir()
    pdf_path = papers / "example.pdf"
    with fitz.open() as doc:
        p1 = doc.new_page()
        p1.insert_text((72, 72), "Vessel noise affects whale communication.")
        p2 = doc.new_page()
        p2.insert_text((72, 72), "Signals can be masked by ambient noise.")
        doc.save(pdf_path)
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    manifest = [{"id": "P99", "local_pdf_filename": "example.pdf", "title": "Synthetic test paper", "doi": "10.0/test", "sha256": digest, "pdf_page_count": 2}]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return papers, manifest_path, pdf_path


def test_normalization_retains_lines_and_non_ascii():
    assert normalize_text("  Ocean\t noise  \r\n\r\n  10 µPa  ") == "Ocean noise\n\n10 μPa"


def test_ingestion_keeps_page_ids_and_source_metadata(tmp_path):
    papers, manifest, _ = sample_corpus(tmp_path)
    output = tmp_path / "output"
    report = ingest(papers, manifest, output)
    items = [json.loads(row) for row in (output / "pages.jsonl").read_text(encoding="utf-8").splitlines()]
    assert report["papers"] == 1 and report["pages"] == 2
    assert [r["page_id"] for r in items] == ["P99:p0001", "P99:p0002"]
    assert [r["pdf_page"] for r in items] == [1, 2]
    assert all(r["source_id"] == "P99" for r in items)
    assert "Vessel noise" in items[0]["text"]
    assert "Signals" in items[1]["text"]
    assert (output / "ingestion_report.json").is_file()


def test_mutated_pdf_fails_closed(tmp_path):
    papers, manifest, pdf_path = sample_corpus(tmp_path)
    pdf_path.write_bytes(pdf_path.read_bytes() + b"changed")
    out = tmp_path / "out"
    with pytest.raises(IngestionError, match="Checksum mismatch"):
        ingest(papers, manifest, out)
    assert not (out / "pages.jsonl").exists()


def test_missing_pdf_fails_closed(tmp_path):
    papers, manifest, pdf_path = sample_corpus(tmp_path)
    pdf_path.unlink()
    with pytest.raises(IngestionError, match="Missing PDF"):
        ingest(papers, manifest, tmp_path / "out")


def test_invalid_manifest_path_traversal_rejected(tmp_path):
    papers, manifest, _ = sample_corpus(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data[0]["local_pdf_filename"] = "../escape.pdf"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(IngestionError, match="Unsafe PDF filename"):
        ingest(papers, manifest, tmp_path / "out")


def test_unknown_reading_order_rejected(tmp_path):
    papers, manifest, _ = sample_corpus(tmp_path)
    with pytest.raises(IngestionError, match="Unknown reading order"):
        ingest(papers, manifest, tmp_path / "out", reading_order="magic")
