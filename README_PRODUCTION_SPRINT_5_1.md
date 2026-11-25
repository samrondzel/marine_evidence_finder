# Production Deployment — Sprint 5.1: CI and container acceptance

## Scope

This replaces the earlier `.github/workflows/ci.yml` (which may already exist in your Git working tree). It gates container builds on tests. It does **not** publish images, deploy to a server, open ports to the internet or use paid OpenAI calls. Registry delivery, deployment, auth, TLS, backups and production secrets are later increments. Existing application code, models, retrieval, volumes and Compose settings remain unchanged.

## Two independent jobs

1. **Python 3.11 + PostgreSQL integration**: GitHub-hosted Ubuntu 24.04, isolated PostgreSQL 16 service on port 5433 with database `marine_evidence_test`, path guard, install `requirements-ci.txt`, `alembic upgrade head`, full pytest and deterministic agent smoke. The five existing live DB tests are now enabled. The old hard-coded migration revision 0002 was stale; the test now compares against the migration tree head and verifies the jobs table. Semantic tests use NumPy test encoders, not model downloads.
2. **Docker build + full stack smoke**: starts only after the first job passes. Creates an isolated temporary directory containing selected application files, generated synthetic PDFs and a minimal base corpus. Builds the existing API, UI, worker/reconciler and migration images. Starts DB/Redis, applies migrations, starts the full stack, checks API/search, uploads a synthetic PDF via the real HTTP endpoint, waits for RQ to complete, checks the uploaded PDF and search result, Prometheus scrape, heartbeat, UI health and Grafana cost dashboard provisioning. On failure, prints container status and bounded logs. The shell script refuses to run outside a GitHub-hosted runner; cleanup uses only its unique CI project name and disposable volumes.

Both jobs run on push/PR/manual trigger with read-only token permissions, checkout credentials not persisted, no OpenAI secret, timeouts and cancellation of superseded runs. Action references use official v6 major tags; immutable SHA pins and dependency lockfiles are follow-up supply-chain work. Pip cache is a download cache, not a preinstalled environment or lockfile.

## Install and local checks (PowerShell)

```powershell
git status --short
Expand-Archive "$env:USERPROFILE\Downloads\marine_production_sprint5_1_ci.zip" -DestinationPath . -Force
python -m pytest -q
python scripts/smoke_agent.py
python scripts/check_ci_inputs.py
```

The reconstructed archive with all previous patches produced **196 passed, 5 skipped** (Python 3.13, original reviewed corpus available; live PostgreSQL disabled). The offline agent smoke, Bash syntax check and YAML parse passed. A clean checkout without the reviewed original P05 corpus skips the two corpus-specific tests; with the five live DB tests enabled in CI, the expected count is 199 passed / 2 skipped if no additional local tests are present. These are expectations, not a hosted CI result. The build/test runner has no Docker daemon, PostgreSQL or network access for dependency installation here, so the full workflow is unexecuted until you push it.

## Before any push

The original project archive contained a local `.env` file. Do not commit it, or private PDFs, uploads, chunks, local archives and generated benchmark outputs. `.gitignore` now excludes those paths, but does NOT untrack existing files or remove old commits. `python scripts/check_ci_inputs.py` lists forbidden tracked paths without printing contents. If it fails, stop and review. Do not bulk remove files or rewrite history automatically. Check `git log --all -- .env` too; if a real key was ever committed, rotate it before pushing or changing visibility. The path guard is not a content scanner or proof that history is secret-free. Keep the remote private until reviewed. Do not add OpenAI credentials to Actions secrets for this sprint.

Inspect changes to `.gitignore` and `.github/workflows/ci.yml` in case you had local customization. Stage the patch explicitly rather than `git add .`:

```powershell
git add -- .github/workflows/ci.yml .gitignore requirements-ci.txt scripts/check_ci_inputs.py scripts/prepare_ci_stack.py scripts/ci_compose_smoke.sh scripts/ci_stack_smoke.py scripts/smoke_observability.py tests/test_postgres_live.py tests/test_ci_pipeline.py README_PRODUCTION_SPRINT_5_1.md AGENTIC_EVALUATION_REPORT.md
python scripts/check_ci_inputs.py
# Only proceed if the guard passes and staged files are expected.
git diff --cached --stat
git commit -m "ci: test PostgreSQL and smoke-test the container stack"
git remote -v
# If an upstream is already configured and is the intended remote:
git push
```

If earlier application code/overlays were not committed, review and stage their source/config/test files as a separate commit before pushing; never push the archives or `.env`. If no upstream exists, configure the intended private repository first. If the guard fails, do not push and send the list of paths (never secrets).

## Hosted acceptance

Open GitHub repository → Actions → CI - Marine Evidence Finder. Both jobs should be green. Check that the PostgreSQL tests ran rather than skipped, and Docker job logs show the synthetic ingestion and Grafana checks. No live OpenAI calls are made. The existing user Docker stack does not need to be rebuilt or restarted. Grafana panels for LLM usage may have no data in CI, by design; provisioning is checked, not paid traffic. Separately inspect those panels on your local stack after the earlier paid benchmark if desired.

After a successful run, a safe negative control is an intentionally failing test on a throwaway branch: the `test` job must fail and `docker-smoke` must be skipped. Remove that branch afterwards. Do not intentionally break main or expose the current unauthenticated application. Required checks/branch protection can then be configured on the remote.

## Limitations

This is CI, not continuous deployment. Images are built but not pushed. GitHub-hosted runner billing/quotas and dependency availability apply. Dependencies and base images still use ranges/tags, not fully reproducible digests. No paid end-to-end LLM regression, external vulnerability scan, registry publication, cloud deployment, TLS, authentication or production backup is included. The synthetic fixture checks functionality, not scientific quality or production scale.
