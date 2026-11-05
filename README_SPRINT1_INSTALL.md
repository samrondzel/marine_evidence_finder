# Hackathon #2 — Sprint 1 patch installation

This is an **overlay**, not a replacement project. It changes one existing file and adds two files plus two docs:

- `src/marine_evidence/api.py` (edited)
- `src/marine_evidence/config.py` (new)
- `tests/test_app_config.py` (new)
- `ARCHITECTURE_AUDIT_SPRINT_1.md` (new)
- `README_SPRINT1_INSTALL.md` (new)

## Windows PowerShell

Run in your existing `marine-evidence-finder` project root. Since the project is clean, optionally create a branch first:

```powershell
git switch -c feature/production-backend
Expand-Archive "$env:USERPROFILE\Downloads\marine_backend_sprint1_overlay.zip" -DestinationPath . -Force
python -m pytest -q
```

Expected: **82 passed** if the source/test suite matches the snapshot uploaded for review.

Restart your existing API server, then open:

- http://127.0.0.1:8000/health
- http://127.0.0.1:8000/health/live
- http://127.0.0.1:8000/health/ready
- http://127.0.0.1:8000/docs

Use PowerShell to check the new endpoint:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

**Default local configuration is unchanged.** `CorpusStore` still uses `data/chunks/word_safe/chunks.jsonl`, `papers`, and `data/app`. The environment variables listed in the architecture audit can override them without modifying source code.

**Do not expose this API publicly yet.** It has no authentication or rate limiting; `/ask` can incur API charges.

### Interview checkpoint

Why does our existing `threading.RLock` not make the app safe to run with 4 Uvicorn worker processes?
