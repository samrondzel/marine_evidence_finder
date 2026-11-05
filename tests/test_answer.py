import json
from types import SimpleNamespace
import pytest
from marine_evidence.bm25 import BM25Index
from marine_evidence.answer import (
    AnswerError, validate_answer, answer_question, call_openai, format_evidence, render,
)


HIT = {"rank": 1, "score": 1.0, "chunk_id": "P01:p0001:c0001", "source_id": "P01",
       "pdf_page": 1, "filename": "paper.pdf", "title": "Paper", "doi": "10.1/test",
       "text": "Vessel noise coincided with higher whistle frequency."}


def make_index():
    return BM25Index([HIT])


def test_grounded_answer_and_citation_render():
    def generator(question, hits, model):
        return {"status": "answered", "reason": "", "claims": [
            {"statement": "Whistle frequency was higher.", "citation_ids": [HIT["chunk_id"]]}]}
    out = answer_question("vessel noise whistle", make_index(), generator=generator)
    assert out["status"] == "answered" and len(out["citations"]) == 1
    assert "[P01 p.1]" in render(out)


def test_invalid_citation_rejected():
    with pytest.raises(AnswerError, match="Unknown citation"):
        validate_answer({"status": "answered", "reason": "", "claims": [
            {"statement": "Unsupported", "citation_ids": ["OTHER:p1:c1"]}]}, [HIT])


def test_unsourced_claim_rejected():
    with pytest.raises(AnswerError):
        validate_answer({"status": "answered", "reason": "", "claims": [
            {"statement": "Unsourced", "citation_ids": []}]}, [HIT])


def test_reject_unsupported_number_as_claim():
    with pytest.raises(AnswerError):
        validate_answer({"status": "insufficient_evidence", "reason": "No evidence", "claims": [
            {"statement": "42 calves died", "citation_ids": [HIT["chunk_id"]]}]}, [HIT])


def test_empty_query_and_no_hit_no_api():
    with pytest.raises(AnswerError):
        answer_question("", make_index())
    out = answer_question("unfindable_zword", make_index())
    assert out["status"] == "insufficient_evidence"
    assert not out["citations"]


def test_openai_payload_and_structured_output_via_fake_client():
    class FakeResponses:
        def __init__(self): self.kwargs = None
        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(status="completed", output_text=json.dumps({
                "status": "answered", "claims": [{"statement": "Whistles rose", "citation_ids": [HIT["chunk_id"]]}],
                "reason": ""}))
    responses = FakeResponses()
    client = SimpleNamespace(responses=responses)
    output = call_openai("vessel whistles?", [HIT], client=client, model="test-model")
    assert output["status"] == "answered"
    assert responses.kwargs["store"] is False
    assert responses.kwargs["text"]["format"]["strict"] is True
    assert "untrusted" in responses.kwargs["instructions"].lower()
    assert HIT["chunk_id"] in responses.kwargs["input"]


def test_reject_incorrect_structure():
    with pytest.raises(AnswerError):
        validate_answer({"status": "answered", "reason": "", "claims": [], "extra": 1}, [HIT])


def test_answered_with_nonempty_reason_is_normalized_not_rejected():
    raw = {"status": "answered", "reason": "The cited study describes the effect.",
           "claims": [{"statement": "Whistle frequency was higher.",
                       "citation_ids": [HIT["chunk_id"]]}]}
    output = validate_answer(raw, [HIT])
    assert output["status"] == "answered"
    assert output["reason"] == ""
    assert output["claims"] == raw["claims"]
    assert raw["reason"]  # Do not mutate the original API response.


def test_answered_with_reason_still_rejects_invalid_citations():
    raw = {"status": "answered", "reason": "Explanation",
           "claims": [{"statement": "A claim", "citation_ids": ["invented-id"]}]}
    with pytest.raises(AnswerError, match="Unknown citation ID"):
        validate_answer(raw, [HIT])


def test_api_answered_with_nonempty_reason_keeps_citations():
    class FakeResponses:
        def create(self, **kwargs):
            return SimpleNamespace(status="completed", output_text=json.dumps({
                "status": "answered", "reason": "Because it is documented in the cited passage.",
                "claims": [{"statement": "Whistle frequency was higher.",
                            "citation_ids": [HIT["chunk_id"]]}]}))
    response = call_openai("What did dolphins change?", [HIT],
                           client=SimpleNamespace(responses=FakeResponses()), model="test-model")
    assert response["reason"] == ""
    assert response["claims"][0]["citation_ids"] == [HIT["chunk_id"]]
