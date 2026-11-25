#!/usr/bin/env bash
set -euo pipefail
# Deliberately NOT a local deployment script. All destructive cleanup is scoped
# to the unique CI project on a disposable GitHub-hosted runner.
if [[ "${GITHUB_ACTIONS:-}" != true || "${RUNNER_ENVIRONMENT:-}" != github-hosted || ! "${GITHUB_RUN_ID:-}" =~ ^[0-9]+$ || ! "${GITHUB_RUN_ATTEMPT:-}" =~ ^[0-9]+$ ]]; then
  echo 'Refusing to run outside a GitHub-hosted Actions runner.' >&2
  exit 1
fi
repo=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d "${RUNNER_TEMP:?}/marine-ci.XXXXXX")
root="$work/stack"
python "$repo/scripts/prepare_ci_stack.py" "$root"
project="marine-ci-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
cd "$root"
cfg=(docker compose --project-name "$project" --env-file "$root/ci.env"
  -f compose.yaml -f compose.postgres.yaml -f compose.metadata.yaml
  -f compose.jobs.yaml -f compose.observability.yaml -f "$repo/compose.ci-images.yaml")
export OPENAI_API_KEY='' MARINE_DB_PASSWORD=local_ci_only
cleanup() {
  rc=$?
  trap - EXIT
  if (( rc != 0 )); then
    "${cfg[@]}" ps -a || true
    "${cfg[@]}" logs --no-color --tail 120 || true
  fi
  "${cfg[@]}" down --volumes --remove-orphans || true
  exit "$rc"
}
trap cleanup EXIT
"${cfg[@]}" config --quiet
"${cfg[@]}" build api ui db-migrate
"${cfg[@]}" up -d --wait --wait-timeout 120 db redis
"${cfg[@]}" run --rm --no-deps db-migrate
"${cfg[@]}" up -d --no-build --wait --wait-timeout 180
python "$repo/scripts/smoke_api.py"
python "$repo/scripts/smoke_ingestion_jobs.py" "$root/ci-upload.pdf" --timeout 120
python "$repo/scripts/smoke_observability.py"
python "$repo/scripts/ci_stack_smoke.py" "$root"

# Verify the running containers really used the image IDs that will be exported.
for service in api worker reconciler ui; do
  image=marine-ci-runtime:tested
  [[ "$service" != ui ]] || image=marine-ci-ui:tested
  container=$("${cfg[@]}" ps -q "$service")
  [[ -n "$container" ]]
  [[ $(docker inspect --format '{{.Image}}' "$container") == $(docker image inspect --format '{{.Id}}' "$image") ]]
done
# Only main push/manual runs set this variable. Export BEFORE cleanup, AFTER smoke.
if [[ -n "${MARINE_CI_IMAGE_EXPORT:-}" ]]; then
  [[ "$GITHUB_REF" == refs/heads/main && ( "$GITHUB_EVENT_NAME" == push || "$GITHUB_EVENT_NAME" == workflow_dispatch ) ]]
  mkdir -p "$MARINE_CI_IMAGE_EXPORT"
  (
    cd "$MARINE_CI_IMAGE_EXPORT"
    for role in runtime ui migrations; do
      printf '%s %s\n' "$role" "$(docker image inspect --format '{{.Id}}' "marine-ci-${role}:tested")"
    done > image-ids.txt
    docker image save marine-ci-runtime:tested marine-ci-ui:tested marine-ci-migrations:tested | gzip -1 > images.tar.gz
    sha256sum images.tar.gz image-ids.txt > SHA256SUMS
  )
fi
