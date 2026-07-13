#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/mnt/d/AI-Workspace/Projects/crypto-quant-nfi}"
PID_FILE="$PROJECT_ROOT/user_data/freqtrade-testnet.pid"
LOG_FILE="$PROJECT_ROOT/user_data/logs/freqtrade-testnet.log"
DB_FILE="$PROJECT_ROOT/user_data/tradesv3.testnet.sqlite"

echo "=== Testnet status ==="
if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE")"
  if kill -0 "$pid" 2>/dev/null; then
    echo "TESTNET_RUNNING=True"
    echo "PID=$pid"
  else
    echo "TESTNET_RUNNING=False"
    echo "STALE_PID=$pid"
  fi
else
  echo "TESTNET_RUNNING=False"
fi
echo "PID_FILE=$PID_FILE"
echo "LOG_FILE=$LOG_FILE"
echo "DB_FILE=$DB_FILE"
[[ -f "$LOG_FILE" ]] && tail -n 40 "$LOG_FILE" || true
