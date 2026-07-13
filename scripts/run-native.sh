#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/native-env.sh"
ensure_runtime_config_ready
"$VENV_ROOT/bin/python" "$PROJECT_ROOT/scripts/test-ccxt-proxy.py"
activate_venv
ensure_native_safety
exec freqtrade trade \
  --config "$RUNTIME_CONFIG_PATH" \
  --userdir "$PROJECT_ROOT/user_data" \
  --strategy "$STRATEGY_NAME" \
  --strategy-path "$PROJECT_ROOT/user_data/strategies" \
  --db-url "$DB_URL" \
  --logfile "$LOG_FILE"
