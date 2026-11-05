# ADR-001 — Local Docker Compose deployment

**Status:** accepted for Mini-Hackathon #2, Docker Sprint.

## Context

Marine Evidence Finder has a Python FastAPI backend, Streamlit UI, a static corpus (8 scientific PDFs, 238 original chunks) and mutable uploaded PDFs/index. The original system uses host-local files, and `CorpusStore` protects in-process writes with a `threading.RLock`.

## Decision

1. Use **two Compose services** with a shared Python image: `api` and `ui`.
2. Publish only on `127.0.0.1` to keep this unauthenticated teaching MVP on the host.
3. Use host bind mounts for the original corpus (`:ro`) and the existing mutable `data/app` directory (`:rw`) to preserve user uploads.
4. Use `--workers 1` until document metadata and index updates are coordinated across processes.
5. Run the image as an unprivileged user. Copy only code and dependency manifests into the image.
6. Split `MARINE_API_URL` (container-to-container DNS) from `MARINE_PUBLIC_API_URL` (browser-facing links).
7. Use readiness health checks and start Streamlit only after API health is confirmed.

## Alternatives considered

- **Single container running both processes:** simpler startup, but mixes responsibility and loses independent service health.
- **Named Docker volume for uploads:** portable to Linux hosts, but initially hides existing `data/app` uploads without an import/migration. A bind mount is better for this incremental transition.
- **Expose API port on all interfaces:** unnecessary for local use and risky without authentication.
- **Four workers for higher throughput:** incorrect with in-memory indexes and process-local locks; can produce stale reads and lost registry updates.
- **Introduce PostgreSQL immediately:** rejected for this sprint to isolate infrastructure changes from persistence redesign.

## Verification and caveats

- Existing test suite: 82 passed before Docker Sprint; 87 passed after adding five checks.
- Runtime API against the supplied snapshot: 9 documents, 286 chunks, uploaded PDF served successfully (the extra 48 chunks came from an existing upload).
- Compose YAML parsed successfully with PyYAML; there was **no Docker Engine available for a live container deployment** in the assistant environment.
- We have NOT measured containerized performance, resource use, actual restart behavior, or security readiness.

## Interview practice

**Question:** Why does a `127.0.0.1:8000:8000` port mapping coexist with `--host 0.0.0.0` in the container?

**Key idea:** the app listens on all *container interfaces* so the UI service can reach it via Docker networking; Docker publishes that container port only to the host's loopback interface, preventing general LAN access. The two addresses refer to different network namespaces.
