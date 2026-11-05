# Sprint 4 — CI + read-only API smoke test

A standalone overlay to add automated tests to your current Marine Evidence Finder without altering the PostgreSQL integration, Docker Compose, or CorpusStore.

## Why?

- **Local `pytest`** tells you whether the tests pass on **your machine**.
- **CI (continuous integration)** runs them on a **clean GitHub runner** on every push and pull request.
- **Smoke testing** quickly checks the **running API** (`/health/ready` or `/health`, `/documents`, `/search`).
- This is **not CD**. Nothing is automatically deployed. The CI job does **not** start PostgreSQL or run real database integration tests yet.

## Install (PowerShell, in project root)

Save/commit existing work first, then extract this ZIP to the project root:

```powershell
Expand-Archive "$env:USERPROFILE\Downloads\marine_ci_sprint4_overlay.zip" -DestinationPath . -Force
```

The ZIP adds exactly these files:

- `.github/workflows/ci.yml`
- `scripts/smoke_api.py`
- `README_CI_SPRINT_4.md`

## Verify locally

```powershell
python -m pytest -q
python scripts/smoke_api.py --base-url http://127.0.0.1:8000
```

For the smoke test, start your current Docker Compose API first. The script will fail with exit code 1 when the API is unavailable or has an unexpected response; it does not upload/delete files or call `/ask` (paid).

## Enable GitHub Actions

Ensure that the project is a Git repo **on GitHub**. Then:

```powershell
git status
git add .github/workflows/ci.yml scripts/smoke_api.py README_CI_SPRINT_4.md
git commit -m "ci: run pytest on push and pull requests"
git push
```

Open the GitHub repository's **Actions** tab and select the **CI — tests** workflow. On new pushes and PRs it should run automatically; a manual run is also available via `workflow_dispatch`.

## What CI does

1. Checks out the repository on a clean GitHub-hosted Ubuntu machine.
2. Installs Python 3.11.
3. Installs your editable package, test, app and answer dependencies; installs `requirements-db.txt` when present.
4. Runs `python -m pytest -q` with an empty `OPENAI_API_KEY` to prevent real LLM API requests.

**Green on your laptop does not imply green on GitHub.** If CI fails because fixture files such as `data/chunks/word_safe/chunks.jsonl` were not committed, inspect the failure and decide whether to version a small, non-sensitive test fixture or generate it in CI. Never commit `.env`, tokens or private PDFs to make a test pass.

## Next increment: real PostgreSQL integration tests

When the current versions of `compose.postgres.yaml`, `compose.metadata.yaml`, migrations, and repository tests are available, add a PostgreSQL service to CI and test against a fresh actual DB (migrations + repository CRUD + restart behavior). Those changes are intentionally **not** guessed from the older archive.
