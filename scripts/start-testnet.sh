#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "$PROJECT_ROOT"
export PROJECT_ROOT

source "$PROJECT_ROOT/scripts/native-env.sh"

PID_FILE="$PROJECT_ROOT/user_data/freqtrade-testnet.pid"
LOG_FILE="$PROJECT_ROOT/user_data/logs/freqtrade-testnet.log"
DB_URL="sqlite:///$PROJECT_ROOT/user_data/tradesv3.testnet.sqlite"
CONFIG="$PROJECT_ROOT/user_data/config.testnet.local.json"

mkdir -p "$PROJECT_ROOT/user_data/logs" "$PROJECT_ROOT/reports/testnet_run"
bash "$PROJECT_ROOT/scripts/build-testnet-config.sh"
python3 "$PROJECT_ROOT/scripts/testnet_safety_audit.py"

if [[ -z "${BINANCE_TESTNET_KEY:-}" || -z "${BINANCE_TESTNET_SECRET:-}" ]]; then
  echo "TESTNET_KEY_MISSING"
  echo "Not starting testnet bot without BINANCE_TESTNET_KEY and BINANCE_TESTNET_SECRET."
  exit 0
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "TESTNET_ALREADY_RUNNING=True"
  exit 0
fi

activate_venv
export FREQTRADE__EXCHANGE__KEY="$BINANCE_TESTNET_KEY"
export FREQTRADE__EXCHANGE__SECRET="$BINANCE_TESTNET_SECRET"
export FREQTRADE__DRY_RUN=false
export FREQTRADE__TRADING_MODE=spot
unset FREQTRADE__MARGIN_MODE
unset FREQTRADE__CAN_SHORT

nohup freqtrade trade \
  --config "$CONFIG" \
  --userdir "$PROJECT_ROOT/user_data" \
  --strategy "$STRATEGY_NAME" \
  --strategy-path "$PROJECT_ROOT/user_data/strategies" \
  --db-url "$DB_URL" \
  --logfile "$LOG_FILE" \
  > "$PROJECT_ROOT/reports/testnet_run/testnet_stdout.log" 2>&1 &

echo $! > "$PID_FILE"
echo "TESTNET_STARTED=True"
echo "PID_FILE=$PID_FILE"
echo "LOG_FILE=$LOG_FILE"
