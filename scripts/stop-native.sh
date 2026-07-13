#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/native-env.sh"

SYSTEM_SERVICE="crypto-quant-nfi.service"
stopped_any=false

if systemctl status >/dev/null 2>&1 && [[ -f "/etc/systemd/system/$SYSTEM_SERVICE" ]]; then
  systemctl stop "$SYSTEM_SERVICE" || true
  if systemctl is-active --quiet "$SYSTEM_SERVICE"; then
    die "systemd system service did not stop"
  fi
  rm -f "$PID_FILE"
  echo "[PASS] Stopped systemd system service"
  stopped_any=true
fi

if systemctl --user status >/dev/null 2>&1 && systemctl --user list-unit-files "$SYSTEM_SERVICE" >/dev/null 2>&1; then
  systemctl --user stop "$SYSTEM_SERVICE" || true
  if systemctl --user is-active --quiet "$SYSTEM_SERVICE"; then
    die "systemd user service did not stop"
  fi
  rm -f "$PID_FILE"
  echo "[PASS] Stopped systemd user service"
  stopped_any=true
fi

config_paths=(
  "$PROJECT_ROOT/user_data/config.runtime.json"
  "$PROJECT_ROOT/user_data/config.sample_validation.json"
)
stopped_process=false
for config_path in "${config_paths[@]}"; do
  pattern="freqtrade trade --config $config_path"
  pids="$(pgrep -f "$pattern" || true)"
  for pid in $pids; do
    if [[ "$pid" != "$$" ]]; then
      kill "$pid" || true
      stopped_process=true
    fi
  done
done
if [[ "$stopped_process" == true ]]; then
  for _ in {1..20}; do
    still_running=false
    for config_path in "${config_paths[@]}"; do
      if pgrep -f "freqtrade trade --config $config_path" >/dev/null; then
        still_running=true
      fi
    done
    [[ "$still_running" == false ]] && break
    sleep 1
  done
  for config_path in "${config_paths[@]}"; do
    if pgrep -f "freqtrade trade --config $config_path" >/dev/null; then
      die "Freqtrade dry-run process did not stop"
    fi
  done
  rm -f "$PID_FILE"
  echo "[PASS] Stopped dry-run process"
  exit 0
fi

if [[ "$stopped_any" == true ]]; then
  exit 0
fi

if [[ ! -f "$PID_FILE" ]]; then
  echo "[PASS] Not running (no PID file)"
  exit 0
fi
pid="$(cat "$PID_FILE")"
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  for _ in {1..20}; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    die "Process $pid did not stop"
  fi
fi
rm -f "$PID_FILE"
echo "[PASS] Stopped"
