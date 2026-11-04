import json
from pathlib import Path

import numpy as np
import pytest

from marine_evidence.bm25 import SearchError
from marine_evidence.semantic import (
    search_text, _encode, build_index, open_index, SemanticIndex, _length_warning,
)
from scripts.compare_retrievers_dev import compare


class ToyEncoder:
    """Deterministic test double, NOT a real semantic model."""
    def encode(self, texts, **kwargs):
        vectors = []
        for text in texts:
            tokens = text.lower()
            if any(w in tokens for w in ("feeding", "foraging", "prey")):
                v = [1., 0., 0.]
            elif any(w in tokens for w in ("whistle", "vocal", "call")):
                v = [0., 1., 0.]
            else:
                v = [0., 0., 1.]
            vectors.append(v)
        return np.asarray(vectors, dtype=np.float32)


def chunks():
    return [
        {"chunk_id": "P01:p0001:c0001", "text": "The whales changed their foraging behaviour", "source_id": "P01", "pdf_page": 1,
         "title": "Study A", "filename": "a.pdf", "doi": "10.123/a", "start_char": 0, "end_char": 42},
        {"chunk_id": "P01:p0001:c0002", "text": "Prey capture attempts were reduced", "source_id": "P01", "pdf_page": 1,
         "title": "Study A", "filename": "a.pdf", "doi": "10.123/a", "start_char": 20, "end_char": 54},
        {"chunk_id": "P02:p0003:c0001", "text": "Dolphin whistle changes", "source_id": "P02", "pdf_page": 3,
         "title": "Study B", "filename": "b.pdf", "doi": "10.123/b", "start_char": 0, "end_char": 24},
    ]


def write_chunks(path: Path):
    path.write_text("".join(json.dumps(c) + "\n" for c in chunks()), encoding="utf-8")


def test_soft_wrap_normalized_for_encoding_but_not_for_citation():
    raw = "The adja-\ncent boats were near vessel-noise."
    assert search_text(raw) == "The adjacent boats were near vessel-noise."
    assert "adja-\ncent" in raw


def test_build_and_load_semantic_embeddings(tmp_path):
    corpus = tmp_path / "chunks.jsonl"
    write_chunks(corpus)
    store = tmp_path / "index"
    meta = build_index(corpus, store, encoder=ToyEncoder(), model_name="unit-test-model")
    assert meta["chunk_count"] == 3
    assert meta["embedding_dimension"] == 3
    assert (store / "vectors.npy").is_file()
    index, loaded = open_index(corpus, store, encoder=ToyEncoder())
    assert loaded["chunk_sha256"] == meta["chunk_sha256"]
    hits = index.search("feeding activity", top_k=2)
    assert hits[0]["source_id"] == "P01"
    assert hits[0]["rank"] == 1
    assert hits[0]["text"] == chunks()[0]["text"]
    assert len(index.search(" ")) == 0


def test_distinct_pages_and_ranking(tmp_path):
    corpus = tmp_path / "chunks.jsonl"
    write_chunks(corpus)
    store = tmp_path / "index"
    build_index(corpus, store, encoder=ToyEncoder(), model_name="unit-test-model")
    index, _ = open_index(corpus, store, encoder=ToyEncoder())
    assert len(index.search("feeding", top_k=3)) == 3
    result = index.search("feeding", top_k=3, distinct_pages=True)
    assert [(r["source_id"], r["pdf_page"]) for r in result] == [("P01", 1), ("P02", 3)]
    assert result[0]["chunk_id"] == "P01:p0001:c0001"  # stable tie order


def test_stale_index_is_rejected(tmp_path):
    corpus = tmp_path / "chunks.jsonl"
    write_chunks(corpus)
    store = tmp_path / "index"
    build_index(corpus, store, encoder=ToyEncoder(), model_name="unit-test-model")
    corpus.write_text(corpus.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(SearchError, match="STALE INDEX"):
        open_index(corpus, store, encoder=ToyEncoder())


def test_bad_shapes_and_zero_vectors_raise():
    with pytest.raises(SearchError, match="Vector count/dimension"):
        SemanticIndex(chunks(), np.ones((2, 3), dtype="float32"), ToyEncoder())
    with pytest.raises(SearchError, match="not L2-normalized"):
        SemanticIndex(chunks(), np.ones((3, 3), dtype="float32"), ToyEncoder())


def test_invalid_top_k_and_empty_question(tmp_path):
    corpus = tmp_path / "chunks.jsonl"
    write_chunks(corpus)
    store = tmp_path / "index"
    build_index(corpus, store, encoder=ToyEncoder(), model_name="unit-test-model")
    index, _ = open_index(corpus, store, encoder=ToyEncoder())
    with pytest.raises(SearchError, match="top_k"):
        index.search("feeding", top_k=0)
    assert not index.search("   ")


def test_toy_encoder_prefixes_for_asymmetric_retrieval():
    class CaptureEncoder(ToyEncoder):
        def encode(self, texts, **kwargs):
            self.calls.append(texts)
            return super().encode(texts, **kwargs)
    enc = CaptureEncoder()
    enc.calls = []
    _encode(enc, ["passage: whales", "passage: dolphins"], 2)
    assert enc.calls[0][0].startswith("passage: ")


def test_evaluation_only_dev_and_unchanged_bm25(tmp_path):
    corpus = tmp_path / "chunks.jsonl"
    write_chunks(corpus)
    store = tmp_path / "index"
    build_index(corpus, store, encoder=ToyEncoder(), model_name="unit-test-model")
    benchmark = tmp_path / "benchmark.jsonl"
    rows = [
        {"id": "Q01", "split": "dev", "task_type": "fact", "question": "feeding", "answerability": "answerable", "source_ids": ["P01"],
         "evidence": [{"source_id": "P01", "pdf_page": 1, "evidence_role": "support"}]},
        {"id": "Q02", "split": "dev", "task_type": "abstention", "question": "penguins", "answerability": "not_supported_by_corpus", "source_ids": [], "evidence": []},
        {"id": "Q03", "split": "test", "task_type": "fact", "question": "ocean", "answerability": "answerable", "source_ids": ["P999"], "evidence": []},
    ]
    benchmark.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    data = compare(corpus, store, benchmark, encoder=ToyEncoder())
    assert len(data["per_question"]) == 2
    assert [r["id"] for r in data["predictions_semantic"]] == ["Q01", "Q02"]
    assert data["semantic"]["mean_direct_page_recall"] == 1.
    assert data["bm25"]["mean_direct_page_recall"] == 0.  # lexical search does not know feeding ~ foraging


def test_length_diagnostic_with_fake_encoder():
    assert _length_warning(ToyEncoder(), ["passage: x"])["max_model_tokens"] is None
