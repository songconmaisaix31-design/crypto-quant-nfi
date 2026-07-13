#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NFI_DIR="$PROJECT_ROOT/vendor/NostalgiaForInfinity"
CONFIG_FILE="$PROJECT_ROOT/user_data/config.json"

die() {
  echo "[FAIL] $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

strategy_name() {
  if [[ -n "${FREQTRADE__STRATEGY:-}" ]]; then
    echo "$FREQTRADE__STRATEGY"
    return
  fi
  if [[ -f "$PROJECT_ROOT/.env" ]]; then
    local env_strategy
    env_strategy="$(grep -E '^FREQTRADE__STRATEGY=' "$PROJECT_ROOT/.env" | tail -1 | cut -d= -f2- || true)"
    if [[ -n "$env_strategy" ]]; then
      echo "$env_strategy"
      return
    fi
  fi
  if [[ -f "$NFI_DIR/docker-compose.yml" ]]; then
    local compose_strategy
    compose_strategy="$(grep -Eo 'FREQTRADE__STRATEGY:-NostalgiaForInfinityX[0-9]+' "$NFI_DIR/docker-compose.yml" | head -1 | sed 's/.*:-//' || true)"
    if [[ -n "$compose_strategy" && -f "$NFI_DIR/${compose_strategy}.py" ]]; then
      echo "$compose_strategy"
      return
    fi
  fi
  find "$NFI_DIR" -maxdepth 1 -type f -name 'NostalgiaForInfinityX*.py' -printf '%f\n' \
    | sed 's/\.py$//' | sort -V | tail -1
}

ensure_dry_run_config() {
  python3 - "$CONFIG_FILE" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    cfg = json.load(f)
errors = []
if cfg.get("dry_run") is not True:
    errors.append("dry_run must be true")
if cfg.get("trading_mode") != "spot":
    errors.append("trading_mode must be spot")
if cfg.get("margin_mode") not in ("", None):
    errors.append("margin_mode must be empty")
if cfg.get("can_short") is True:
    errors.append("can_short must not be true")
exchange = cfg.get("exchange", {})
if exchange.get("key") or exchange.get("secret") or exchange.get("password"):
    errors.append("exchange credentials must be empty")
if errors:
    for err in errors:
        print(f"[FAIL] {err}", file=sys.stderr)
    sys.exit(1)
print("[PASS] dry_run=true, spot mode, no exchange credentials")
PY
}

compose() {
  docker compose "$@"
}

