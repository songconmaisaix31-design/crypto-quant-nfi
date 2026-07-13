#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

require_cmd docker
require_cmd python3

docker --version >/dev/null
docker compose version >/dev/null
echo "[PASS] Docker available"

compose config >/dev/null
echo "[PASS] Docker Compose config valid"

[[ -f "$CONFIG_FILE" ]] || die "Missing user_data/config.json"
python3 -m json.tool "$CONFIG_FILE" >/dev/null
echo "[PASS] Freqtrade config JSON valid"
ensure_dry_run_config

strategy="$(strategy_name)"
[[ -f "$NFI_DIR/${strategy}.py" ]] || die "Missing NFI strategy: ${strategy}.py"
echo "[PASS] NFI strategy exists: ${strategy}"

if grep -RInE 'FREQTRADE__EXCHANGE__(KEY|SECRET|PASSWORD)=.{12,}|\"(key|secret|password)\"[[:space:]]*:[[:space:]]*\"[^\"[:space:]]{12,}\"' "$PROJECT_ROOT/.env" "$CONFIG_FILE" 2>/dev/null \
  | grep -v 'API_SERVER' | grep -v 'override-from-env'; then
  die "Suspicious real exchange credential found"
fi
echo "[PASS] No real exchange API key found"

test -w "$PROJECT_ROOT/user_data/data" || die "Data directory is not writable"
test -w "$PROJECT_ROOT/user_data/logs" || die "Logs directory is not writable"
echo "[PASS] Data and log directories writable"

compose run --rm freqtrade list-strategies --config /freqtrade/user_data/config.json --strategy-path /freqtrade/user_data/strategies/nfi \
  | tee "$PROJECT_ROOT/user_data/logs/validate-list-strategies.log" \
  | grep -q "$strategy"
echo "[PASS] NFI strategy loadable by Freqtrade"

