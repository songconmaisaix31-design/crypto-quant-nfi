#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

require_cmd docker
require_cmd git
require_cmd python3

docker --version
docker compose version
git --version

mkdir -p "$PROJECT_ROOT/user_data/strategies" "$PROJECT_ROOT/user_data/data" "$PROJECT_ROOT/user_data/backtest_results" "$PROJECT_ROOT/user_data/logs" "$PROJECT_ROOT/vendor"

if [[ ! -d "$NFI_DIR/.git" ]]; then
  rm -rf "$NFI_DIR"
  git clone --depth 1 https://github.com/iterativv/NostalgiaForInfinity.git "$NFI_DIR"
else
  git -C "$NFI_DIR" pull --ff-only
fi

strategy="$(strategy_name)"
[[ -f "$NFI_DIR/${strategy}.py" ]] || die "NFI strategy file not found: ${strategy}.py"

if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
  user="nfi_$(python3 - <<'PY'
import secrets, string
print("".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8)))
PY
)"
  pass="$(python3 - <<'PY'
import secrets, string
alphabet = string.ascii_letters + string.digits + "_"
print("".join(secrets.choice(alphabet) for _ in range(32)))
PY
)"
  jwt="$(python3 - <<'PY'
import secrets, string
alphabet = string.ascii_letters + string.digits + "_"
print("".join(secrets.choice(alphabet) for _ in range(48)))
PY
)"
  ws="$(python3 - <<'PY'
import secrets, string
alphabet = string.ascii_letters + string.digits + "_"
print("".join(secrets.choice(alphabet) for _ in range(48)))
PY
)"
  cat > "$PROJECT_ROOT/.env" <<EOF
TZ=Asia/Shanghai
COMPOSE_PROJECT_NAME=crypto-quant-nfi
FREQTRADE__STRATEGY=${strategy}
FREQTRADE__EXCHANGE__NAME=binance
FREQTRADE__API_SERVER__LISTEN_PORT=8080
FREQTRADE__API_SERVER__USERNAME=${user}
FREQTRADE__API_SERVER__PASSWORD=${pass}
FREQTRADE__API_SERVER__JWT_SECRET_KEY=${jwt}
FREQTRADE__API_SERVER__WS_TOKEN=${ws}
EOF
  chmod 600 "$PROJECT_ROOT/.env"
  echo "[PASS] Generated local .env with random Web UI credentials"
else
  echo "[PASS] Existing .env preserved"
fi

ensure_dry_run_config
compose pull
echo "[PASS] Setup complete. Strategy: ${strategy}"
