#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

ensure_dry_run_config
strategy="$(strategy_name)"
echo "Starting dry-run with strategy: ${strategy}"
compose up -d

sleep 5
compose ps
if ! compose ps --status running | grep -q 'freqtrade'; then
  compose logs --tail=120 freqtrade
  die "Freqtrade container is not running"
fi

if command -v curl >/dev/null 2>&1; then
  curl -fsS "http://127.0.0.1:${FREQTRADE__API_SERVER__LISTEN_PORT:-8080}/api/v1/ping" >/dev/null || true
fi

echo "[PASS] Dry-run started"
echo "Web UI: http://127.0.0.1:${FREQTRADE__API_SERVER__LISTEN_PORT:-8080}"
echo "Logs: make logs"
echo "Stop: make stop"

