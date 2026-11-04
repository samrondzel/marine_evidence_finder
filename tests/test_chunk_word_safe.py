import json

import pytest

from marine_evidence.chunk_word_safe import (
    build, chunk_spans, page_to_chunks, safe_cut_positions,
)


def page(text):
    return {"page_id": "P02:p0003", "source_id": "P02", "pdf_page": 3,
            "title": "Sample", "doi": "10.fake/test", "filename": "sample.pdf", "text": text}


def test_offsets_preserve_original_page_and_max_length():
    text = ("Dolphins respond to vessel noise. " * 190)
    chunks = page_to_chunks(page(text), max_chars=2000, overlap_chars=300)
    assert len(chunks) > 1
    assert chunks[0]["start_char"] == 0
    assert chunks[-1]["end_char"] == len(text)
    for c in chunks:
        assert len(c["text"]) <= 2000
        assert text[c["start_char"]:c["end_char"]] == c["text"]
    for first, second in zip(chunks, chunks[1:]):
        assert 0 < second["start_char"] <= first["end_char"]
        assert first["end_char"] > second["start_char"]  # overlap


def test_soft_wrap_not_separated_even_when_end_near_limit():
    prefix = "dolphin " * 246
    text = prefix + "adja-\ncent " + "noise " * 180
    spans = chunk_spans(text, max_chars=2000, overlap_chars=300)
    wrap_start = text.index("adja-")
    wrap_end = wrap_start + len("adja-\ncent")
    for start, end in spans:
        assert not (wrap_start < start < wrap_end)
        assert not (wrap_start < end < wrap_end)
    assert any("adja-\ncent" in text[a:b] for a, b in spans)


def test_hyphenated_normal_word_still_preserved():
    text = ("ship-induced noise and " * 200) + "vessel-based"
    chunks = page_to_chunks(page(text), 300, 50)
    assert chunks[-1]["end_char"] == len(text)
    assert all(c["text"] == text[c["start_char"]:c["end_char"]] for c in chunks)


def test_short_empty_pages_and_guard_validation():
    assert chunk_spans("") == []
    assert chunk_spans("hello world") == [(0, 11)]
    assert 0 in safe_cut_positions("a-\nb c")
    with pytest.raises(ValueError):
        chunk_spans("hello world", overlap_chars=2000)
    with pytest.raises(ValueError, match="No word-safe boundary"):
        chunk_spans("X" * 2010, 2000, 300)


def test_repeatability_and_build(tmp_path):
    pages = tmp_path / "pages.jsonl"
    source = [page("abc-\ndef " * 200), {**page("Sea noise " * 250), "pdf_page": 4, "page_id": "P02:p0004"}]
    pages.write_text("\n".join(json.dumps(p) for p in source), encoding="utf-8")
    stats1 = build(pages, tmp_path / "out", 400, 50)
    saved1 = (tmp_path / "out" / "chunks.jsonl").read_bytes()
    stats2 = build(pages, tmp_path / "out", 400, 50)
    assert stats1 == stats2
    assert saved1 == (tmp_path / "out" / "chunks.jsonl").read_bytes()
    assert stats1["pages_input"] == 2


def test_no_dangling_letters_at_boundaries():
    text = " ".join("cetacean" for _ in range(1000))
    cuts = safe_cut_positions(text)
    for p in cuts[1:-1]:
        assert text[p - 1].isspace()
    chunks = page_to_chunks(page(text), max_chars=2000, overlap_chars=300)
    for ch in chunks[1:]:
        assert ch["text"].startswith("cetacean")
