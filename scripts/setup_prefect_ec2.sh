#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PREFECT_EXECUTABLE="${PROJECT_ROOT}/.venv-prod/bin/prefect"
export PREFECT_API_URL="http://127.0.0.1:4200/api"

[[ -x "${PREFECT_EXECUTABLE}" ]] || {
  echo "Prefect executable not found at ${PREFECT_EXECUTABLE}." >&2
  exit 1
}
command -v curl >/dev/null 2>&1 || {
  echo "curl is required to check Prefect server health." >&2
  exit 1
}

server_ready=0
for _ in {1..30}; do
  if curl --fail --silent "${PREFECT_API_URL}/health" >/dev/null; then
    server_ready=1
    break
  fi
  sleep 2
done
[[ "${server_ready}" -eq 1 ]] || {
  echo "Prefect server is not healthy at ${PREFECT_API_URL}." >&2
  exit 1
}

cd -- "${PROJECT_ROOT}"
if ! "${PREFECT_EXECUTABLE}" work-pool inspect electricity-pool >/dev/null 2>&1; then
  "${PREFECT_EXECUTABLE}" work-pool create --type process electricity-pool
else
  echo "Prefect work pool electricity-pool already exists."
fi

"${PREFECT_EXECUTABLE}" deploy \
  --prefect-file "${PROJECT_ROOT}/prefect.yaml" \
  --name powerflow-entsoe-pipeline \
  --no-prompt

echo "PowerFlow Prefect deployment applied successfully."
