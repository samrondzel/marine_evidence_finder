import pytest

from marine_evidence.bm25 import SearchError
from marine_evidence.hybrid import HybridIndex


def hit(name, page):
    return {"rank": 0, "chunk_id": name, "source_id": "P01", "pdf_page": page,
            "title": "Demo", "filename": "demo.pdf", "text": name, "score": 0.9}


class FakeIndex:
    def __init__(self, hits):
        self.hits = hits
    def search(self, question, *, top_k, distinct_pages=False):
        assert not distinct_pages
        return self.hits[:top_k]


def make(lex, sem, **kw):
    return HybridIndex(FakeIndex(lex), FakeIndex(sem), **kw)


def test_rrf_promotes_agreed_result():
    h = make([hit("a", 1), hit("b", 2)], [hit("b", 2), hit("a", 1)], bm25_weight=0.5)
    result = h.search("question", top_k=2)
    # Both get equal weighted RRF; stable tie break on ID.
    assert [x["chunk_id"] for x in result] == ["a", "b"]
    assert result[0]["bm25_rank"] == 1
    assert result[0]["semantic_rank"] == 2


def test_weight_one_matches_bm25_ranking():
    h = make([hit("b", 2), hit("a", 1)], [hit("a", 1), hit("b", 2)], bm25_weight=1)
    assert [x["chunk_id"] for x in h.search("Q", top_k=2)] == ["b", "a"]


def test_weight_zero_matches_dense_ranking():
    h = make([hit("b", 2), hit("a", 1)], [hit("a", 1), hit("b", 2)], bm25_weight=0)
    assert [x["chunk_id"] for x in h.search("Q", top_k=2)] == ["a", "b"]


def test_missing_from_one_retriever_still_allowed():
    h = make([hit("a", 1)], [hit("b", 2)], bm25_weight=.5)
    res = h.search("Q", top_k=2)
    assert {x["chunk_id"] for x in res} == {"a", "b"}


def test_page_diversity_after_fusion():
    h = make([hit("a", 1), hit("b", 1), hit("c", 2)],
             [hit("a", 1), hit("b", 1), hit("c", 2)])
    res = h.search("Q", top_k=2, distinct_pages=True)
    assert [x["pdf_page"] for x in res] == [1, 2]


def test_invalid_inputs():
    with pytest.raises(SearchError):
        make([], [], bm25_weight=-0.1)
    with pytest.raises(SearchError):
        make([], [], candidate_k=0)
    with pytest.raises(SearchError):
        make([], [], rrf_k=0)
    with pytest.raises(SearchError):
        make([], []).search("Q", top_k=0)


def test_blank_query():
    assert make([hit("a", 1)], []).search(" ") == []


def test_not_using_cosine_and_bm25_score_values():
    lex = [hit("a", 1)]
    lex[0]["score"] = 1000
    sem = [hit("a", 1)]
    sem[0]["score"] = -4
    result = make(lex, sem).search("Q", top_k=1)
    expected = .75/61 + .25/61
    assert result[0]["score"] == pytest.approx(expected, abs=1e-8)
