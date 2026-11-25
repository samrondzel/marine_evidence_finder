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
  -f compose.jobs.yaml -f compose.observability.yaml)
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
"${cfg[@]}" build api ui worker reconciler db-migrate
"${cfg[@]}" up -d --wait --wait-timeout 120 db redis
"${cfg[@]}" run --rm --no-deps db-migrate
"${cfg[@]}" up -d --no-build --wait --wait-timeout 180
python "$repo/scripts/smoke_api.py"
python "$repo/scripts/smoke_ingestion_jobs.py" "$root/ci-upload.pdf" --timeout 120
python "$repo/scripts/smoke_observability.py"
python "$repo/scripts/ci_stack_smoke.py" "$root"
