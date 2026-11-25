# Sprint 5.2.1–5.2.2 — GHCR, release artifacts and immutable image references

## 0. Scope and safety

This patch extends the existing, successful Sprint 5.1 CI. It publishes application images after a successful main-branch CI run, not on feature branches or pull requests. It does not create a VPS, deploy an application, buy anything, expose ports or change the local Compose configuration used for research. The actual registry run has not been performed in the authoring environment. Keep packages private for now; do not publish the repository or packages merely to avoid configuring authentication.

Before applying: confirm the previous Gitleaks history scans passed, that the revoked OpenAI key is no longer in use, and that any real reused/exposed database password is rotated. Keep the old backup branch local. Never push all branches or mirror the repository. The new scan checks the tracked snapshot, not all historical objects, nested Git repositories or every possible secret.

## 1. Mental model

- **Dockerfile**: build recipe, e.g. FROM, COPY, RUN, USER. It is not an executable container.
- **Image**: packaged filesystem layers plus runtime configuration. Images are reusable. A registry can store these images. The image config digest (local `docker image inspect ... .Id`) is not necessarily the registry manifest digest.
- **Container**: a running or stopped instance of an image with its own writable layer. Several instances can use the same image with different commands and environments.
- **Volume/bind mount**: data outside the image. Replacing a container should not discard durable storage. PostgreSQL data, uploaded PDFs, source PDFs and corpus chunks belong outside the image. Config and prices are also mounted in the current project.
- **Registry**: service implementing image push/pull. GHCR is GitHub Container Registry (`ghcr.io`). A repository in Git stores source code; a package in GHCR stores built images. A package may have its own access rules.
- **Tag**: mutable name pointing to an image manifest. Use versioned tags to discover releases. `latest` is not a reliable version. Even a commit-SHA tag can be overwritten by a registry writer.
- **Digest**: content-addressed identifier of the manifest. Pull by `name@sha256:...` to request that particular artifact; if removed, the pull fails rather than silently using a different version. It is not an attestation or guarantee of safety.

Example (illustrative, not a real published image): `ghcr.io/samrondzel/marine_evidence_finder-runtime:sha-<40-char-sha>-r<run-id>-a<attempt>`. The digest form is `ghcr.io/samrondzel/marine_evidence_finder-runtime@sha256:<64-hex-digits>`.

## 2. Our three images and eight services

| Image | Dockerfile | Services |
|---|---|---|
| runtime | Dockerfile.jobs | api, worker, reconciler |
| ui | Dockerfile | ui |
| migrations | Dockerfile.migrations | db-migrate (one-shot, profile tools) |

PostgreSQL, Redis, Prometheus and Grafana use upstream images as before. Count: 8 long-lived services plus the one-shot migration service. The API, worker and reconciler use the same code and dependencies, but run different commands. The local UI image need not install Redis/Postgres dependencies. Migrations use Alembic and a small separate image. Dockerfiles already copy explicit source/dependency files, not entire repository contents; `.dockerignore` also excludes local corpus and credentials. No runtime environment values are baked into release images by this patch.

## 3. Build once, test and promote

A runner is a disposable machine. GitHub jobs do not share the local Docker daemon. If Job 2 builds an image and Job 3 rebuilds it, the new image might differ even for the same commit (base image tags, unpinned dependency resolution, timestamps). Instead:

1. `test`: existing Python/Postgres tests plus a new secret scan of the tracked checkout.
2. `docker-smoke`: same synthetic fixture, same API/ingestion/observability tests. `compose.ci-images.yaml` gives three explicit local image names. `api`, `worker`, `reconciler` all use `marine-ci-runtime:tested`. The script builds api, ui and db-migrate once each; `--no-build` prevents rebuilding when bringing up the stack. It checks running container image IDs after smoke. The migration command uses the explicitly named local image.
3. On main push or manual main run only, record the three local image IDs, save the images to a compressed tar, and record SHA256 checksums. Upload the bundle as a short-lived GitHub Actions artifact (one day, not a registry release).
4. `publish`: depends on docker-smoke; runs only for main push or manual main run. Download the same-run artifact, verify checksums, load the images into the new daemon, verify IDs, Linux/amd64 platform and OCI labels for repository URL and revision. Authenticate to GHCR, tag, push the three loaded images (no rebuild), and capture the manifest digest returned by Docker push.
5. Only after all three pushes succeed, produce `release.json`, `release.env` and a workflow summary with all digest references. The manifest is uploaded as a separate artifact (30 days). It is not a GitHub Releases object. No deployment happens yet.

`docker save` exports the image layers/config, not the live container, its bind mounts or PostgreSQL volume. Never use `docker commit` of a running container to make a release. Checksums detect transfer mismatch but are not cryptographic provenance signatures. Docker push may publish some packages before a later push fails; such a run is failed and has no complete release manifest. Packages may still contain those partial tags; do not deploy them. Retrying the publish job can reuse the original bundle while retained; after expiration rerun the entire workflow.

## 4. CI files and concepts

### `.github/workflows/ci.yml`

Existing workflow/job names remain unchanged to preserve branch protection. `needs: docker-smoke` is the dependency gate for publishing. `if: github.ref == 'refs/heads/main' && (github.event_name == 'push' || github.event_name == 'workflow_dispatch')` restricts publication to main. On a pull request, both original CI checks must pass; publishing is intentionally skipped. Do not make publish a required PR check. On merge, a new run for main builds and tests the merged commit, then publishes it. If you rerun only failed jobs, the transferred bundle must still be available.

`permissions: contents: read` is the workflow default. The publish job alone gets `packages: write`. GitHub creates `GITHUB_TOKEN` for the workflow job automatically; it is used via an environment variable in the publication step. It is not your OpenAI key, not a personal access token, and must not be printed. Login uses `docker login ghcr.io -u <actor> --password-stdin`; logout happens in `finally`. Existing repo/organization policies can restrict publishing. Keep main protected; someone who can change workflows can change their behavior, so permissions are not a complete trust boundary.

New Gitleaks snapshot check: `git archive HEAD` into a temporary directory, scan with official `ghcr.io/gitleaks/gitleaks:v8.30.1`, mask secrets and scan archives up to depth 3. A finding stops the pipeline. Investigate before adding any narrow exception; never disable the scan or print credentials. The prior manual historical archive scan remains necessary. This check is not a vulnerability scanner and does not prove absence of all secrets.

### `compose.ci-images.yaml`

Append only to the disposable CI Compose config. `image:` specifies the tag to assign when building or use when running. `pull_policy: never` avoids pulling a different app image for these local test tags. The `x-labels` extension and YAML anchor reuse the same `org.opencontainers.image.source` and `org.opencontainers.image.revision` labels for all three builds. Source label helps associate GHCR packages with the repo. The new overlay requires GitHub environment variables and is not intended for local deployment.

### `scripts/ci_compose_smoke.sh`

Changes: build only the three app images; preserve existing health/migrate/ingestion smoke and disposable cleanup; compare running `.Image` and `docker image inspect .Id`; optionally export tested image bundle after all smoke assertions. The script still refuses to run outside GitHub-hosted Actions runners. Never run its `down --volumes` cleanup against your real stack.

### `scripts/publish_tested_images.py`

`release_identity` checks runner, branch, event, commit and run identity. `read_ids` accepts exactly three known roles and valid SHA256 IDs. `inspect_image` verifies transferred identity and labels. `push_digest` validates the digest reported by the push. `publish` orchestrates load, verify, login, tag, push, logout and manifest output. The tag contains full commit SHA, run ID and attempt so normal reruns create new version tags. These tags are not cryptographically immutable; future Compose files will use the recorded digest references. The script does not deploy or add new dependencies.

### `tests/test_release_pipeline.py`

15 unit tests cover identity gating, manual main release, malformed inventories, digest extraction, mocked successful publication, refusing mismatched image IDs before login and failure mid-publication (no complete manifest). Docker calls are mocked here. Real Docker, Actions, Gitleaks and GHCR must still be verified on GitHub. The authoring environment lacks some runtime dependencies, so the entire pytest suite was not rerun there; the previous accepted counts were local 196/5 and CI 199/2.

## 5. Apply and verify locally (PowerShell)

Use the new branch `feature/production-deployment`, based on merged `origin/main`. If already on that branch, do not recreate it. Check `git status --short` first; don't overwrite unrelated work.

```powershell
git branch --show-current
git status --short
# If needed, switch/create main from origin/main and fast-forward, then:
# git switch -c feature/production-deployment
Expand-Archive "$env:USERPROFILE\Downloads\marine_production_sprint5_2_1_ghcr.zip" -DestinationPath . -Force
python -m pytest -q
python scripts/smoke_agent.py
python scripts/check_ci_inputs.py
```

Expected if unchanged since Sprint 5.1: 211 passed / 5 skipped locally; 214 passed / 2 skipped in CI. These are predicted counts, not a full rerun result. Do not rebuild or stop local Docker; the new files target CI.

```powershell
git add -- .github/workflows/ci.yml compose.ci-images.yaml scripts/ci_compose_smoke.sh scripts/publish_tested_images.py tests/test_release_pipeline.py README_PRODUCTION_SPRINT_5_2_1.md
git diff --cached --stat
python scripts/check_ci_inputs.py
git commit -m "Publish smoke-tested container images to GHCR"
git push -u origin feature/production-deployment
```

Open the Actions run. Expect test + docker-smoke green; publish skipped for feature push. If Gitleaks flags a secret, stop and investigate using redacted output only. Open PR into main, wait for required checks; publish is not a required PR check. Merge through the protected branch, then open the NEW main workflow run. That run should have three green jobs. The authoring environment cannot verify your GitHub permissions or package visibility.

## 6. Main acceptance criteria

- Secret scan passed, original jobs passed, and publication runs only on allowed main events.
- Main run summary lists three GHCR package digest references. Packages appear on GitHub under the owner's Packages. GHCR defaults new packages to private; verify and keep them private for now.
- Download the `marine-release-...` artifact from the main run. Check `release.json` and `release.env` for the exact same commit and all three digest references. These are safe metadata (no secrets), but keep them with release records for later use. Do not copy them into `.env` yet.
- For a later pull acceptance check: authenticate to private GHCR using a suitably scoped classic PAT with `read:packages` and `docker login --password-stdin`, not a write token. Do not create that token until needed and do not paste it into chat. If packages are public by deliberate decision, anonymous pull is possible, but this sprint does not require making them public.
- If publishing gets 403/denied, check the repository/organization Actions package policy and package repository association / Manage Actions access. Do not enable broad permissions globally or create a personal write token as the first workaround.

## 7. Limitations and next sprint

Only linux/amd64 application images; no ARM build, no signed attestation/SBOM, no dependency lock or vulnerability scanner yet. Upstream infra images still referenced by tags. GitHub Actions use major-version action tags consistent with prior CI; pinning to audited full SHAs is future supply-chain hardening. Artifacts occupy storage and consume time/bandwidth, especially for private repo quotas. Check actual usage; no VPS or paid LLM call is needed for this sprint. Registry visibility and pricing depend on GitHub settings; no guarantee of zero bill across all plans/quotas. A full release also needs config and corpus provisioning, migration safety, a persistent server, TLS/auth/rate limits, backups, rollback and deployment verification. Old Git history may still contain earlier files and the local backup branch with revoked credentials. No public deployment until security is ready.

## References

- https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images
- https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
- https://docs.docker.com/reference/cli/docker/image/save/
- https://docs.docker.com/reference/cli/docker/compose/build/
- https://docs.docker.com/dhi/explore/security-concepts/digests/
- https://github.com/gitleaks/gitleaks
