#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/mnt/d/AI-Workspace/Projects/crypto-quant-nfi}"
PID_FILE="$PROJECT_ROOT/user_data/freqtrade-testnet.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "TESTNET_RUNNING=False"
  exit 0
fi

pid="$(cat "$PID_FILE")"
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      echo "TESTNET_STOPPED=True"
      exit 0
    fi
    sleep 1
  done
  echo "TESTNET_STOPPED=False"
  exit 2
fi

rm -f "$PID_FILE"
echo "TESTNET_RUNNING=False"
