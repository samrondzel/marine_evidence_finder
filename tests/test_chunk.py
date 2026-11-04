import json
from pathlib import Path
import pytest
from marine_evidence.chunk import ChunkingError, chunk_page, build_chunks


def make_page(text="Sea noise affects dolphin behaviour. " * 90):
    return {"page_id":"P01:p0003", "source_id":"P01", "filename":"a.pdf", "title":"Research", "doi":"10.1/example", "pdf_page":3, "text":text, "char_count":len(text)}


@pytest.mark.parametrize("strategy", ["fixed", "boundary"])
def test_exact_offsets_and_page_provenance(strategy):
    page=make_page()
    chunks=chunk_page(page,max_chars=400,overlap_chars=80,strategy=strategy)
    assert len(chunks)>1
    assert all(c["text"]==page["text"][c["start_char"]:c["end_char"]] for c in chunks)
    assert all(c["page_id"]=="P01:p0003" and c["pdf_page"]==3 for c in chunks)
    assert all(c["char_count"]<=400 and c["start_char"]<c["end_char"] for c in chunks)
    assert chunks[0]["start_char"]==0 and chunks[-1]["end_char"]==len(page["text"])
    assert all(a["end_char"]>=b["start_char"] for a,b in zip(chunks,chunks[1:]))


def test_reproducible_chunk_ids():
    page=make_page()
    assert chunk_page(page,max_chars=500,overlap_chars=100)==chunk_page(page,max_chars=500,overlap_chars=100)
    different=chunk_page(page,max_chars=700,overlap_chars=100)
    assert different[0]["chunk_id"]!=chunk_page(page,max_chars=500,overlap_chars=100)[0]["chunk_id"]


def test_short_and_empty_page():
    short=make_page("Whales communicate.")
    assert len(chunk_page(short,max_chars=400,overlap_chars=40))==1
    assert chunk_page(make_page(""),max_chars=400,overlap_chars=40)==[]


def test_invalid_overlap():
    with pytest.raises(ChunkingError,match="overlap_chars"):
        chunk_page(make_page(),max_chars=400,overlap_chars=400)


def test_modified_page_is_rejected():
    page=make_page()
    page["char_count"]+=1
    with pytest.raises(ChunkingError,match="char_count"):
        chunk_page(page)


def test_build_output_and_provenance(tmp_path:Path):
    pages=tmp_path/"pages.jsonl"
    item=make_page()
    pages.write_text(json.dumps(item)+"\n",encoding="utf-8")
    report=build_chunks(pages,tmp_path/"output",max_chars=400,overlap_chars=80)
    stored=[json.loads(x) for x in (tmp_path/"output/chunks.jsonl").read_text().splitlines()]
    assert report["pages"]==1 and report["chunks"]==len(stored)
    assert stored[0]["source_id"]=="P01"
    assert (tmp_path/"output/chunking_report.json").exists()


def test_duplicate_page_id_fails(tmp_path:Path):
    pages=tmp_path/"pages.jsonl"
    entry=json.dumps(make_page())
    pages.write_text(entry+"\n"+entry+"\n",encoding="utf-8")
    with pytest.raises(ChunkingError,match="duplicate page_id"):
        build_chunks(pages,tmp_path/"out")


def test_no_benchmark_is_used(tmp_path:Path):
    item=make_page()
    pages=tmp_path/"pages.jsonl"
    pages.write_text(json.dumps(item),encoding="utf-8")
    # The index builder only consumes pages; no benchmark is available.
    report=build_chunks(pages,tmp_path/"out")
    assert report["chunks"]>0
