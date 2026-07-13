#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"
export PROJECT_ROOT

REPORT_DIR="$PROJECT_ROOT/reports/testnet_run"
mkdir -p "$REPORT_DIR"
LOG_FILE="$REPORT_DIR/manual_secret_run_logs.txt"
SUMMARY_FILE="$REPORT_DIR/manual_secret_run_summary.json"
REPORT_FILE="$REPORT_DIR/manual_secret_run_report.md"

cleanup() {
  unset BINANCE_TESTNET_KEY || true
  unset BINANCE_TESTNET_SECRET || true
}
trap cleanup EXIT

read -r -s -p "BINANCE_TESTNET_KEY: " BINANCE_TESTNET_KEY
printf "\n"
read -r -s -p "BINANCE_TESTNET_SECRET: " BINANCE_TESTNET_SECRET
printf "\n"
export BINANCE_TESTNET_KEY BINANCE_TESTNET_SECRET

status="TESTNET_KEY_MISSING"
steps=()
run_step() {
  local name="$1"
  shift
  echo "=== $name ===" >> "$LOG_FILE"
  if "$@" >> "$LOG_FILE" 2>&1; then
    steps+=("$name:PASS")
    return 0
  fi
  local rc=$?
  steps+=("$name:FAIL:$rc")
  return "$rc"
}

: > "$LOG_FILE"
if [[ -z "${BINANCE_TESTNET_KEY:-}" || -z "${BINANCE_TESTNET_SECRET:-}" ]]; then
  status="TESTNET_KEY_MISSING"
else
  run_step safety_audit python3 scripts/testnet_safety_audit.py || status="BLOCKED"
  run_step endpoint_audit python3 scripts/testnet_endpoint_audit.py || status="BLOCKED"
  run_step smoke_test bash scripts/testnet-smoke-test.sh || status="TESTNET_KEY_INVALID"
  run_step order_lifecycle bash scripts/testnet-order-lifecycle-check.sh || status="BLOCKED"
  run_step status_before bash scripts/status-testnet.sh || true
  run_step start_testnet bash scripts/start-testnet.sh || status="BLOCKED"
  run_step status_running bash scripts/status-testnet.sh || true
  run_step stop_testnet bash scripts/stop-testnet.sh || status="BLOCKED"
  run_step status_after bash scripts/status-testnet.sh || true
  run_step emergency_stop bash scripts/emergency-stop-check.sh || status="BLOCKED"
  run_step gatekeeper bash scripts/gatekeeper.sh || true
  if grep -q "TESTNET_ORDER_LIFECYCLE=PASS" "$LOG_FILE" && [[ "$status" != "BLOCKED" && "$status" != "TESTNET_KEY_INVALID" ]]; then
    status="TESTNET_ORDER_LIFECYCLE_PASS"
  fi
fi

python3 - "$status" "$SUMMARY_FILE" "$REPORT_FILE" "${steps[@]}" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status = sys.argv[1]
summary_path = Path(sys.argv[2])
report_path = Path(sys.argv[3])
steps = sys.argv[4:]
summary = {
    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "status": status,
    "steps": steps,
    "keys_written_to_disk": False,
    "keys_printed": False,
    "testnet_only": True,
    "real_trading_allowed": False,
    "micro_live_allowed": False,
}
summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
lines = [
    "# Manual Testnet Secret Run",
    "",
    f"Status: `{status}`",
    "",
    "- Keys were read with hidden input.",
    "- Keys were exported only to child processes.",
    "- Keys are unset on exit.",
    "- No real mainnet trading is allowed.",
    "",
    "## Steps",
]
lines += [f"- `{step}`" for step in steps]
report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

echo "MANUAL_TESTNET_SECRET_STATUS=$status"

