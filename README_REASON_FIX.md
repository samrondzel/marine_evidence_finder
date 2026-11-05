# Marine Evidence Finder — Step 4 hotfix: answered + nonempty reason

## What broke

OpenAI Responses API returned structured JSON with `status="answered"`, one or more claims with citation IDs, and nonempty `reason`. `validate_answer()` rejected the response with:

```
ERROR: Answered status requires an empty reason
```

The model did respond; the error occurred in the local post-generation validator.

## Fix

- The system instructions explicitly tell the model to set `reason` to the empty string when `status="answered"`.
- For an `answered` response, after all claims and every `citation_ids` value have been validated against actual retrieved chunks, `validate_answer()` discards surplus non-cited `reason` text and returns `reason=""`.
- `insufficient_evidence` still requires `claims=[]` and a nonempty reason.
- Unknown or missing citations are still rejected. This validates reference identity only, **not factual entailment**.

## Install in PowerShell (project root)

```powershell
Expand-Archive "$env:USERPROFILE\Downloads\marine_answer_reason_fix.zip" -DestinationPath . -Force
python -m pytest -q
```

All 66 tests pass in the assembled project. The patch only updates `src/marine_evidence/answer.py` and `tests/test_answer.py` (and adds this README).

## Retry single question (paid API call)

```powershell
python -m marine_evidence.answer `
  --query "In Blair et al. (2016), what changes in foraging were associated with ship noise?" `
  --model gpt-5-mini `
  --top-k 5
```

Note: retrying invokes the API again and may incur another charge. This patch does not change PDF extraction, chunks, embeddings, or BM25.
