# Marine Evidence Finder — Mini-Hackathon #2, Docker Sprint

The existing FastAPI + Streamlit MVP now runs as **two Docker Compose services**. This is a **local development / interview demonstration**, not a publicly secured production deployment.

## Prerequisites

- Docker Desktop, running with Linux containers (Windows: WSL2 engine is recommended).
- From the project root, the existing files must be present:
  - `data/chunks/word_safe/chunks.jsonl`
  - `evaluation/papers_manifest.json`
  - `papers/` (the original PDFs so source links work)
  - `data/app/` (uploads; if there are none, create this folder)
- `OPENAI_API_KEY` in your existing `.env` file for **paid** generation. The search-only mode works without a key. `.env` must remain uncommitted.
- Stop the previous *non-Docker* FastAPI and Streamlit processes so ports 8000/8501 are free.

## Install (Windows PowerShell)

From your project root:

```powershell
Expand-Archive "$env:USERPROFILE\Downloads\marine_backend_docker_sprint_overlay.zip" -DestinationPath . -Force
.\.venv\Scripts\Activate.ps1
python -m pytest -q
```

Expected: **87 passed** (82 baseline after Sprint 1 + 5 Docker Sprint checks). If you did not install Sprint 1, this overlay also includes the necessary config and test files; the expected count is the same.

## Run

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

- Web interface: http://127.0.0.1:8501
- Swagger UI: http://127.0.0.1:8000/docs
- Readiness check: http://127.0.0.1:8000/health/ready

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/health/ready
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/search -ContentType application/json -Body '{"question":"What changed in humpback whale foraging under ship noise?","top_k":3}'
```

For a healthy original 8-PDF corpus, `chunks` should be >= 238. If you have additional PDF uploads in `data/app/`, the count will be larger; **that is expected**.

## Data and access

The API uses *four bind mounts*:

| Host path | Container path | Permission | Purpose |
|---|---|---|---|
| `./data/chunks/word_safe` | `/app/data/chunks/word_safe` | read-only | Original chunk index |
| `./papers` | `/app/papers` | read-only | Original PDFs for evidence links |
| `./evaluation/papers_manifest.json` | `/app/evaluation/papers_manifest.json` | read-only | Original corpus metadata |
| `./data/app` | `/app/data/app` | read/write | Uploaded PDFs, chunks and registry |

**Your existing uploads remain in the same host folder**. They will survive `docker compose down`, `docker compose up --build`, and image rebuilds. Do not delete `data/app/` unless you intend to remove uploads. Unlike a named Docker volume, this is a **bind mount** for easy inspection and compatibility with your existing local installation.

Docker's internal network exposes the API to Streamlit as `http://api:8000` (the environment variable `MARINE_API_URL`). Your **browser** cannot resolve the internal Docker hostname `api`, so source PDF links use `MARINE_PUBLIC_API_URL=http://127.0.0.1:8000` instead. That second address is specifically for a browser running on the same host.

Both published ports bind to **127.0.0.1 only**. The API itself listens on `0.0.0.0` **inside** its container to accept requests from Streamlit; it is *not* publicly exposed on the host.

The UI container receives **no API key**. Only the API container receives `OPENAI_API_KEY`, passed as a runtime environment variable through Compose's `.env` interpolation. `.dockerignore` prevents `.env`, data and PDFs from being copied into the image. Runtime environment variables are not high-assurance secret management; do not treat this as a secure internet deployment.

## Stop, inspect and restart

```powershell
docker compose logs -f api
docker compose logs -f ui
# Ctrl+C stops following logs (services keep running)
docker compose down
# Uploaded files are still on the host in data/app/
docker compose up -d
```

To test persistence: add a new PDF in the UI, note its filename, run `docker compose down`, then `docker compose up -d`; verify it is still searchable.

## Common issues

- **`docker: command not found`**: install/start Docker Desktop. Confirm `docker version` and `docker compose version`.
- **Port 8000/8501 already allocated**: stop the old local Uvicorn/Streamlit processes before starting Compose.
- **API is unhealthy / missing chunks**: make sure `data/chunks/word_safe/chunks.jsonl` exists on the *host*; check `docker compose logs api`. Starting an app without that corpus is a configuration error, not a BM25 failure.
- **Uploaded PDFs not writable**: the container runs as an unprivileged user (`UID 10001`). On Linux hosts, ensure `data/app/` is writable by this UID. On Windows Docker Desktop, make sure the project directory is shared/mounted properly. Do not switch to a root container just to hide permissions problems.
- **PDF links fail**: confirm the API is accessible in your *browser* at `http://127.0.0.1:8000`, and the PDF exists under `papers/` or `data/app/pdfs/`.
- **`/ask` returns 503 or another API error**: verify `.env` supplies a valid API key. Search mode should still work; API calls are billable.
- **You changed code but see the old behavior**: run `docker compose up --build -d`; no hot reload is enabled.

## Production limitations (deliberately out of scope)

No authentication, rate-limiting, DB transactions, distributed index invalidation, upload malware scanning or resource quotas beyond the existing file/page/text caps. `uvicorn --workers 1` is **intentional**: `CorpusStore` holds mutable in-memory BM25 state and a process-local `threading.RLock`; extra workers do not share the lock or index. PostgreSQL + background indexing/refresh mechanisms belong to later sprints.

No Docker daemon was available in the assistant's sandbox. Unit and local FastAPI integration tests were run, and the Compose YAML was parsed; the **first actual container build/run must be verified with Docker Desktop** using the steps above.
