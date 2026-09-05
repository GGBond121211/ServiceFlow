#!/usr/bin/env bash
set -euo pipefail

url="${1:-http://127.0.0.1:8009/api/v1/health}"
timeout_seconds="${2:-60}"
tmp_file="$(mktemp)"
trap 'status=$?; rm -f "$tmp_file"; exit "$status"' EXIT

deadline=$((SECONDS + timeout_seconds))
while (( SECONDS < deadline )); do
  if curl --silent --show-error --fail --connect-timeout 2 --max-time 5 "$url" >"$tmp_file" 2>/dev/null \
    && grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"' "$tmp_file"; then
    cat "$tmp_file"
    exit 0
  fi
  sleep 2
done

echo "healthcheck timeout: $url" >&2
exit 70
