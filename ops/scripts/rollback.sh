#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
previous_image="${1:-${SERVICEFLOW_PREVIOUS_IMAGE:-}}"
if [[ -z "$previous_image" ]]; then
  echo "usage: $0 <previous-image-tag>" >&2
  exit 64
fi

if ! docker image inspect "$previous_image" >/dev/null 2>&1; then
  echo "previous image is not available locally: $previous_image" >&2
  exit 69
fi

compose=(docker compose --project-directory "$root_dir" -f "$root_dir/compose.yaml")
tmp_env="$(mktemp)"
trap 'status=$?; rm -f "$tmp_env"; exit "$status"' EXIT
printf 'SERVICEFLOW_IMAGE=%s\n' "$previous_image" >"$tmp_env"

set -a
source "$tmp_env"
set +a
"${compose[@]}" up -d --no-build --force-recreate
"$root_dir/ops/scripts/healthcheck.sh" "${SERVICEFLOW_HEALTH_URL:-http://127.0.0.1:8009/api/v1/health}" "${SERVICEFLOW_HEALTH_TIMEOUT:-120}"
"${compose[@]}" ps
