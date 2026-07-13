#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/native-env.sh"
ensure_native_safety
"$PROJECT_ROOT/scripts/build-runtime-config.sh"
days="${DAYS:-920}"
pairs=(BTC/USDT ETH/USDT SOL/USDT XRP/USDT ADA/USDT)
frames=(5m 15m 1h 4h 1d)
if freqtrade_native download-data --config "$RUNTIME_CONFIG_PATH" --userdir "$PROJECT_ROOT/user_data" --pairs "${pairs[@]}" --days "$days" --no-parallel-download --prepend --timeframes "${frames[@]}"; then
  find "$PROJECT_ROOT/user_data/data" -type f | sort | tee "$PROJECT_ROOT/user_data/logs/downloaded-data-files.txt"
  du -sh "$PROJECT_ROOT/user_data/data"
else
  echo "[WARN] Freqtrade API download failed; use make download-archive and make import-archive as fallback" >&2
  exit 1
fi