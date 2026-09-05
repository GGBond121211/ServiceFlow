#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compose=(docker compose --project-directory "$root_dir" -f "$root_dir/compose.yaml")
trap 'status=$?; if (( status != 0 )); then echo "deploy failed; inspect: docker compose logs --tail=100" >&2; fi; exit "$status"' EXIT

"${compose[@]}" config --quiet
"${compose[@]}" build
"${compose[@]}" up -d
"$root_dir/ops/scripts/healthcheck.sh" "${SERVICEFLOW_HEALTH_URL:-http://127.0.0.1:8009/api/v1/health}" "${SERVICEFLOW_HEALTH_TIMEOUT:-120}"
"${compose[@]}" ps
