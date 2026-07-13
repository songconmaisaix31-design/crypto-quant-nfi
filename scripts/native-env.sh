#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/mnt/d/AI-Workspace/Projects/crypto-quant-nfi}"
RUNTIME_ROOT="${RUNTIME_ROOT:-$HOME/.local/share/crypto-quant-nfi}"
FREQTRADE_ROOT="${FREQTRADE_ROOT:-$RUNTIME_ROOT/freqtrade}"
VENV_ROOT="${VENV_ROOT:-$FREQTRADE_ROOT/.venv}"
CONFIG_PATH="${CONFIG_PATH:-$PROJECT_ROOT/user_data/config.native.json}"
RUNTIME_CONFIG_PATH="${RUNTIME_CONFIG_PATH:-$PROJECT_ROOT/user_data/config.runtime.json}"
STRATEGY_NAME="${STRATEGY_NAME:-NostalgiaForInfinityX7}"
NFI_ROOT="$PROJECT_ROOT/vendor/NostalgiaForInfinity"
PID_FILE="$PROJECT_ROOT/user_data/freqtrade-native.pid"
LOG_FILE="$PROJECT_ROOT/user_data/logs/freqtrade-native.log"
DB_URL="sqlite:///$PROJECT_ROOT/user_data/tradesv3.dryrun.sqlite"

die() {
  echo "[FAIL] $*" >&2
  exit 1
}

info() {
  echo "[INFO] $*"
}

load_local_env() {
  if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/.env"
    set +a
    unset FREQTRADE__EXCHANGE__NAME
    unset FREQTRADE__STRATEGY
  fi
}

activate_venv() {
  [[ -x "$VENV_ROOT/bin/freqtrade" ]] || die "Freqtrade not installed at $VENV_ROOT. Run ./scripts/setup-native.sh"
  # shellcheck disable=SC1091
  source "$VENV_ROOT/bin/activate"
}

json_get() {
  python3 - "$CONFIG_PATH" "$1" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
cur = cfg
for part in sys.argv[2].split("."):
    cur = cur.get(part) if isinstance(cur, dict) else None
print("" if cur is None else cur)
PY
}

ensure_native_safety() {
  load_local_env
  python3 - "$CONFIG_PATH" <<'PY'
import json, os, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
exchange = cfg.get("exchange", {})
errors = []
if cfg.get("dry_run") is not True:
    errors.append("dry_run must be true")
if cfg.get("trading_mode") != "spot":
    errors.append("trading_mode must be spot")
if cfg.get("margin_mode") not in ("", None):
    errors.append("margin_mode must be empty")
if cfg.get("can_short") is True:
    errors.append("can_short must not be true")
if exchange.get("key") or exchange.get("secret") or exchange.get("password"):
    errors.append("exchange credentials must be empty")
for key in ("FREQTRADE__EXCHANGE__KEY", "FREQTRADE__EXCHANGE__SECRET", "FREQTRADE__EXCHANGE__PASSWORD"):
    if os.environ.get(key):
        errors.append(f"{key} must be empty")
if os.environ.get("FREQTRADE__DRY_RUN", "").lower() in ("0", "false", "no"):
    errors.append("FREQTRADE__DRY_RUN must not disable dry-run")
if os.environ.get("FREQTRADE__TRADING_MODE", "").lower() not in ("", "spot"):
    errors.append("FREQTRADE__TRADING_MODE must be spot when set")
if os.environ.get("FREQTRADE__MARGIN_MODE"):
    errors.append("FREQTRADE__MARGIN_MODE must be empty")
if os.environ.get("FREQTRADE__CAN_SHORT", "").lower() in ("1", "true", "yes"):
    errors.append("FREQTRADE__CAN_SHORT must not enable shorting")
if os.environ.get("FREQTRADE__API_SERVER__LISTEN_IP_ADDRESS", "127.0.0.1") != "127.0.0.1":
    errors.append("FREQTRADE__API_SERVER__LISTEN_IP_ADDRESS must be 127.0.0.1 when set")
api = cfg.get("api_server", {})
if api.get("listen_ip_address") != "127.0.0.1":
    errors.append("api_server.listen_ip_address must be 127.0.0.1")
if errors:
    for err in errors:
        print(f"[FAIL] {err}", file=sys.stderr)
    sys.exit(1)
print("[PASS] Native safety: dry_run=true, spot, no keys, localhost API")
PY
}

ensure_runtime_config_ready() {
  if [[ ! -f "$RUNTIME_CONFIG_PATH" ]]; then
    "$PROJECT_ROOT/scripts/build-runtime-config.sh"
    return
  fi
  python3 - "$RUNTIME_CONFIG_PATH" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
exchange = cfg.get("exchange", {})
api = cfg.get("api_server", {})
errors = []
if cfg.get("dry_run") is not True:
    errors.append("runtime dry_run must be true")
if cfg.get("trading_mode") != "spot":
    errors.append("runtime trading_mode must be spot")
if cfg.get("margin_mode") not in ("", None):
    errors.append("runtime margin_mode must be empty")
if cfg.get("can_short") is True:
    errors.append("runtime can_short must not be true")
for key in ("key", "secret", "password"):
    if exchange.get(key):
        errors.append(f"runtime exchange.{key} must be empty")
if api.get("listen_ip_address") != "127.0.0.1":
    errors.append("runtime api_server.listen_ip_address must be 127.0.0.1")
if errors:
    for err in errors:
        print(f"[FAIL] {err}", file=sys.stderr)
    sys.exit(1)
print("[PASS] Existing runtime config safety verified; not rewriting runtime config")
PY
}

freqtrade_native() {
  load_local_env
  activate_venv
  freqtrade "$@"
}
