#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/native-env.sh"
load_local_env
activate_venv
ensure_native_safety
ensure_runtime_config_ready
"$VENV_ROOT/bin/python" "$PROJECT_ROOT/scripts/test-ccxt-proxy.py"

SYSTEM_SERVICE="crypto-quant-nfi.service"

if systemctl status >/dev/null 2>&1 && [[ -f "/etc/systemd/system/$SYSTEM_SERVICE" ]]; then
  systemctl --user stop "$SYSTEM_SERVICE" >/dev/null 2>&1 || true
  systemctl daemon-reload
  systemctl start "$SYSTEM_SERVICE"
  sleep 12
  systemctl --no-pager --full status "$SYSTEM_SERVICE"
  systemctl is-active --quiet "$SYSTEM_SERVICE" || die "systemd system service failed to start"
  echo "[PASS] Dry-run started with systemd system service"
  echo "Web UI: http://127.0.0.1:8080"
  exit 0
fi

if systemctl --user status >/dev/null 2>&1 && [[ -f "$HOME/.config/systemd/user/$SYSTEM_SERVICE" ]]; then
  systemctl --user daemon-reload
  systemctl --user start "$SYSTEM_SERVICE"
  sleep 12
  systemctl --user --no-pager --full status "$SYSTEM_SERVICE"
  systemctl --user is-active --quiet "$SYSTEM_SERVICE" || die "systemd user service failed to start"
  echo "[PASS] Dry-run started with systemd user service"
  echo "Web UI: http://127.0.0.1:8080"
  exit 0
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  die "Already running with PID $(cat "$PID_FILE")"
fi

rm -f "$PID_FILE"
nohup "$PROJECT_ROOT/scripts/run-native.sh" \
  > "$PROJECT_ROOT/user_data/logs/freqtrade-native.nohup.log" 2>&1 &
echo $! > "$PID_FILE"
sleep 12
if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  tail -120 "$LOG_FILE" "$PROJECT_ROOT/user_data/logs/freqtrade-native.nohup.log" 2>/dev/null || true
  die "Freqtrade failed to start"
fi
echo "[PASS] Dry-run started PID=$(cat "$PID_FILE")"
echo "Web UI: http://127.0.0.1:8080"
