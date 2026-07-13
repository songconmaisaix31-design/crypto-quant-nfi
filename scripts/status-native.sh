#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/native-env.sh"

SYSTEM_SERVICE="crypto-quant-nfi.service"

echo "Project: $PROJECT_ROOT"
echo "Runtime: $RUNTIME_ROOT"
if [[ -x "$VENV_ROOT/bin/freqtrade" ]]; then
  "$VENV_ROOT/bin/freqtrade" --version
else
  echo "Freqtrade: not installed"
fi
echo "Strategy: $STRATEGY_NAME"
echo "Exchange: $(json_get exchange.name 2>/dev/null || echo unknown)"
echo "Dry-run: $(json_get dry_run 2>/dev/null || echo unknown)"
pattern="freqtrade trade --config $RUNTIME_CONFIG_PATH"
status_json="$("$PROJECT_ROOT/scripts/dry_run_status.py" --json 2>/dev/null || true)"
if [[ -n "$status_json" ]]; then
  python3 - "$status_json" <<'PY'
import json
import sys
status = json.loads(sys.argv[1])
mode_labels = {
    "systemd_system_service": "running (systemd system service)",
    "systemd_user_service": "running (systemd user service)",
    "hidden_windows_wsl_carrier": "running (hidden Windows wsl.exe carrier)",
    "freqtrade_trade_process": "running (freqtrade trade process)",
    "pid_file_process": "running (PID file process)",
    "none": "stopped",
}
print(f"Status: {mode_labels.get(status['running_mode'], status['status'])}")
print(f"Dry-run status: {status['status']}")
print(f"Dry-run mode: {status['running_mode']}")
print(f"Forward evidence blocked: {status['forward_evidence_blocked']}")
print(f"Systemd system active: {status['systemd_system'].get('active')}")
print(f"Systemd user active: {status['systemd_user'].get('active')}")
print(f"Freqtrade trade processes: {len(status['freqtrade_trade_processes'])}")
print(f"Hidden Windows wsl.exe carrier detected: {status['hidden_windows_wsl_carrier']['detected']}")
print(f"API health reachable: {status['api_health'].get('reachable')}")
print(f"Active config: {status['active_config']}")
print(f"Active pair count: {status['active_pair_count']}")
PY
elif systemctl status >/dev/null 2>&1 && systemctl is-active --quiet "$SYSTEM_SERVICE"; then
  echo "Status: running (systemd system service)"
elif pgrep -f "$pattern" >/dev/null; then
  echo "Status: running (WSL background process)"
else
  echo "Status: stopped"
  echo "Forward evidence blocked: True"
fi
echo "Web UI: http://127.0.0.1:8080"
echo "Log: $LOG_FILE"
echo "DB: $PROJECT_ROOT/user_data/tradesv3.dryrun.sqlite"
