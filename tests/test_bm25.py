import json
import math
from pathlib import Path

import pytest

from marine_evidence.bm25 import BM25Index, SearchError, read_chunks, tokenize
from scripts.eval_bm25_dev import evaluate


def chunk(cid, text, source="P01", page=1):
    return {"chunk_id": cid, "text": text, "source_id": source, "pdf_page": page,
            "title": "Title", "filename": "file.pdf", "doi": "doi"}


def test_tokenization_lowercase_hyphenated_and_unicode():
    assert tokenize("Vessel noise adja-\ncent behaviour") == ["vessel", "noise", "adjacent", "behaviour"]
    assert tokenize("HUMPBACK 105 dB") == ["humpback", "105", "db"]


def test_idf_and_exact_bm25_for_single_matching_term():
    docs = [chunk("a", "whale whale"), chunk("b", "ship")]
    idx = BM25Index(docs)
    assert idx.n_docs == 2 and idx.avgdl == 1.5
    score = idx.search("whale")[0]["score"]
    expected = math.log1p((2-1+0.5)/(1+0.5)) * (2*(1.5+1)) / (2 + 1.5*(1-0.75+0.75*2/1.5))
    assert score == pytest.approx(expected, abs=1e-6)


def test_ranking_matches_lexical_evidence_and_metadata():
    idx = BM25Index([chunk("a", "boats sailing"), chunk("b", "whales whistle noise", "P02", 3)])
    result = idx.search("whale whistle noise")
    assert result[0]["chunk_id"] == "b"
    assert result[0]["source_id"] == "P02" and result[0]["pdf_page"] == 3


def test_distinct_pages_removes_overlapping_repeats():
    idx = BM25Index([chunk("a", "noise noise", "P01", 1), chunk("b", "noise noise", "P01", 1),
                     chunk("c", "noise", "P02", 2)])
    assert len(idx.search("noise", top_k=3)) == 3
    result = idx.search("noise", top_k=3, distinct_pages=True)
    assert [(r["source_id"], r["pdf_page"]) for r in result] == [("P01",1),("P02",2)]


def test_unmatched_query_empty_and_invalid_k():
    idx = BM25Index([chunk("a", "one boat")])
    assert idx.search("penguins") == []
    with pytest.raises(SearchError):
        idx.search("boat", top_k=0)


def test_read_chunks_reject_duplicate(tmp_path):
    p = tmp_path / "chunks.jsonl"
    p.write_text("\n".join(json.dumps(chunk("a", "noise")) for _ in range(2)),encoding="utf8")
    with pytest.raises(SearchError,match="duplicate"):
        read_chunks(p)


def test_evaluate_dev_only_and_unsupported_excluded():
    idx = BM25Index([chunk("a", "ship noise", "P01", 2)])
    rows = [
        {"id":"Q01", "split":"dev", "task_type":"fact", "question":"ship", "answerability":"answerable", "source_ids":["P01"], "evidence":[{"source_id":"P01","pdf_page":2,"evidence_role":"support"}]},
        {"id":"Q02", "split":"dev", "task_type":"abstention", "question":"penguin", "answerability":"not_supported_by_corpus"},
        {"id":"Q03", "split":"test", "task_type":"fact", "question":"seal", "answerability":"answerable", "source_ids":["P02"], "evidence":[]},
    ]
    pred, summary = evaluate(idx,rows)
    assert [p["id"] for p in pred] == ["Q01","Q02"]
    assert summary["questions"] == 2 and summary["answerable_scored"] == 1
    assert summary["mean_direct_page_recall"] == 1 and summary["unsupported_not_scored"] == 1
