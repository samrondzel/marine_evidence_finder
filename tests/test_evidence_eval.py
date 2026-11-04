from marine_evidence.evidence_eval import normalize_quote, quote_in_chunk, evaluate_dev


def make_chunk(text, page=1, cid="S:p0001:c0001"):
    return {"chunk_id": cid, "source_id": "S", "pdf_page": page,
            "title": "Example", "filename": "example.pdf", "text": text}


def test_normalised_quote_match():
    assert quote_in_chunk("ship noise    raises\nfrequency", "The ship noise raises frequency quickly")
    assert not quote_in_chunk("ship noise lowers frequency", "ship noise raises frequency")


def test_only_support_matters_and_only_dev():
    chunks = [make_chunk("ship noise raises frequency in noisy waters")]
    dev = {"id": "Q01", "split": "dev", "answerability": "answerable", "task_type": "fact",
           "question": "What raises frequency?", "evidence": [
               {"source_id": "S", "pdf_page": 1, "evidence_role": "support", "quote": "ship noise raises frequency"},
               {"source_id": "S", "pdf_page": 1, "evidence_role": "method", "quote": "noisy waters"}]}
    test = {**dev, "id": "QT", "split": "test", "evidence": [
        {"source_id": "S", "pdf_page": 1, "evidence_role": "support", "quote": "not present"}]}
    result = evaluate_dev(chunks, [dev, test])
    assert result["answerable_count"] == 1
    assert result["support_quotes"] == 1
    assert result["quotes_found_in_top_k"] == 1


def test_same_page_not_same_quote():
    chunks = [make_chunk("ship noise raises frequency but not about hormones")]
    data = [{"id": "Q01", "split": "dev", "answerability": "answerable", "task_type": "fact",
             "question": "ship noise hormones", "evidence": [
                 {"source_id": "S", "pdf_page": 1, "evidence_role": "support", "quote": "no such evidence in this chunk"}]}]
    result = evaluate_dev(chunks, data)
    assert result["micro_quote_recall"] == 0
    assert result["any_quote_hit_rate"] == 0
