"""Offline regression tests — no Hugging Face downloads are required."""
from __future__ import annotations

import json

import numpy as np
import pytest

from marine_evidence.bm25 import SearchError
from marine_evidence.semantic import (GTE_MODEL, DEFAULT_MODEL, build_index,
                                     encoding_profile, open_index)
from scripts.compare_models_dev import compare


class StubEncoder:
    def __init__(self):
        self.seen = []
        self.max_seq_length = 8192
        self.tokenizer = None

    def encode(self, inputs, **kwargs):
        self.seen.extend(inputs)
        vectors = []
        for s in inputs:
            if "foraging" in s.lower():
                vectors.append([1., 0., 0.])
            elif "noise" in s.lower():
                vectors.append([0., 1., 0.])
            else:
                vectors.append([0., 0., 1.])
        return np.asarray(vectors, dtype=np.float32)


def save_chunks(path):
    chunks = [
        {"chunk_id":"P01:p0001:c0001", "source_id":"P01", "pdf_page":1,
         "title":"A", "filename":"a.pdf", "doi":"doi-a", "text":"Ship noise alters foraging"},
        {"chunk_id":"P02:p0002:c0001", "source_id":"P02", "pdf_page":2,
         "title":"B", "filename":"b.pdf", "doi":"doi-b", "text":"Dolphin vocalizations"},
    ]
    path.write_text("".join(json.dumps(row)+"\n" for row in chunks), encoding="utf-8")


def test_profiles_are_model_specific():
    assert encoding_profile(GTE_MODEL) == ("", "")
    assert encoding_profile(DEFAULT_MODEL) == ("passage: ", "query: ")


def test_gte_build_and_search_no_e5_prefixes(tmp_path):
    path = tmp_path / "chunks.jsonl"
    save_chunks(path)
    enc = StubEncoder()
    m = build_index(path, tmp_path / "gte", model_name=GTE_MODEL, encoder=enc)
    assert m["query_prefix"] == ""
    assert m["document_prefix"] == ""
    assert not any(t.startswith(("query: ", "passage: ")) for t in enc.seen)
    loaded, _ = open_index(path, tmp_path / "gte", encoder=enc)
    hits = loaded.search("foraging", top_k=2)
    assert hits[0]["source_id"] == "P01"
    assert enc.seen[-1] == "foraging"


def test_e5_build_and_load_preserves_asymmetric_prompts(tmp_path):
    path = tmp_path / "chunks.jsonl"
    save_chunks(path)
    enc = StubEncoder()
    m = build_index(path, tmp_path / "e5", model_name=DEFAULT_MODEL, encoder=enc)
    assert m["document_prefix"] == "passage: "
    assert m["query_prefix"] == "query: "
    loaded, _ = open_index(path, tmp_path / "e5", encoder=enc)
    loaded.search("foraging")
    assert enc.seen[0].startswith("passage: ")
    assert enc.seen[-1].startswith("query: ")


def test_old_e5_index_without_profile_fields_can_still_load(tmp_path):
    path = tmp_path / "chunks.jsonl"
    save_chunks(path)
    d = tmp_path / "e5"
    build_index(path, d, model_name=DEFAULT_MODEL, encoder=StubEncoder())
    m = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
    m.pop("document_prefix")
    m.pop("query_prefix")
    (d / "metadata.json").write_text(json.dumps(m), encoding="utf-8")
    index, _ = open_index(path, d, encoder=StubEncoder())
    assert index.search("foraging", top_k=1)[0]["source_id"] == "P01"


def test_mismatched_profile_is_rejected(tmp_path):
    path = tmp_path / "chunks.jsonl"
    save_chunks(path)
    d = tmp_path / "gte"
    build_index(path, d, model_name=GTE_MODEL, encoder=StubEncoder())
    m = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
    m["query_prefix"] = "query: "
    (d / "metadata.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(SearchError, match="encoding profile"):
        open_index(path, d, encoder=StubEncoder())


def test_head_to_head_filters_test_labels(tmp_path):
    path = tmp_path / "chunks.jsonl"
    save_chunks(path)
    e5_dir, gte_dir = tmp_path / "e5", tmp_path / "gte"
    build_index(path, e5_dir, model_name=DEFAULT_MODEL, encoder=StubEncoder())
    build_index(path, gte_dir, model_name=GTE_MODEL, encoder=StubEncoder())
    gold = tmp_path / "bench.jsonl"
    gold.write_text("\n".join(json.dumps(r) for r in [
        {"id":"Q01","split":"dev","task_type":"fact","question":"foraging",
         "answerability":"answerable","source_ids":["P01"],
         "evidence":[{"source_id":"P01","pdf_page":1,"evidence_role":"support"}]},
        {"id":"Q99","split":"test","task_type":"fact","question":"vocalizations",
         "answerability":"answerable","source_ids":["P99"],
         "evidence":[{"source_id":"P99","pdf_page":8,"evidence_role":"support"}]},
    ])+"\n", encoding="utf-8")
    result = compare(path, e5_dir, gte_dir, gold, e5_encoder=StubEncoder(), gte_encoder=StubEncoder())
    assert result["split"] == "dev"
    assert len(result["per_question"]) == 1
    assert result["per_question"][0]["id"] == "Q01"
    assert len(result["methods"]["gte"]["predictions"]) == 1
    assert result["methods"]["bm25"]["support_only_page_recall"] == 1.0
    assert result["methods"]["gte"]["support_only_page_recall"] == 1.0


def test_wrong_index_identity_fails_closed(tmp_path):
    path = tmp_path / "chunks.jsonl"
    save_chunks(path)
    e5_dir, gte_dir = tmp_path / "e5", tmp_path / "gte"
    build_index(path, e5_dir, model_name=GTE_MODEL, encoder=StubEncoder())
    build_index(path, gte_dir, model_name=DEFAULT_MODEL, encoder=StubEncoder())
    bench = tmp_path / "bench.jsonl"
    bench.write_text('''{"id":"Q01","split":"dev","task_type":"fact","question":"foraging","answerability":"answerable","source_ids":["P01"],"evidence":[{"source_id":"P01","pdf_page":1,"evidence_role":"support"}]}\n''', encoding="utf-8")
    with pytest.raises(SearchError, match="--e5-index"):
        compare(path, e5_dir, gte_dir, bench, e5_encoder=StubEncoder(), gte_encoder=StubEncoder())
