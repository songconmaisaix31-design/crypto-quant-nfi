#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

ensure_dry_run_config
strategy="$(strategy_name)"
days="${DAYS:-180}"
pairs="${PAIRS:-BTC/USDT ETH/USDT BNB/USDT SOL/USDT XRP/USDT}"
timeframes="${TIMEFRAMES:-5m 15m 1h 4h 1d}"
exchange="$(python3 - "$CONFIG_FILE" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["exchange"]["name"])
PY
)"

echo "Downloading ${days} days from ${exchange}"
echo "Strategy: ${strategy}"
echo "Pairs: ${pairs}"
echo "Timeframes: ${timeframes}"

compose run --rm freqtrade download-data \
  --config /freqtrade/user_data/config.json \
  --strategy "$strategy" \
  --strategy-path /freqtrade/user_data/strategies/nfi \
  --exchange "$exchange" \
  --days "$days" \
  --pairs $pairs \
  -t $timeframes

count="$(find "$PROJECT_ROOT/user_data/data" -type f | wc -l | tr -d ' ')"
echo "[PASS] Data directory: $PROJECT_ROOT/user_data/data"
echo "[PASS] Data files: $count"

