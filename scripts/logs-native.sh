#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/native-env.sh"
if systemctl --user status >/dev/null 2>&1 && systemctl --user list-unit-files crypto-quant-nfi.service >/dev/null 2>&1; then
  journalctl --user -u crypto-quant-nfi.service -n 200 -f
else
  tail -n 200 -f "$LOG_FILE"
fi
