#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/mnt/d/AI-Workspace/Projects/crypto-quant-nfi}"
cd "$PROJECT_ROOT"

if [[ -f "$PROJECT_ROOT/scripts/native-env.sh" ]]; then
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/scripts/native-env.sh"
fi

if declare -F activate_venv >/dev/null 2>&1; then
  activate_venv
elif [[ -x "$HOME/.local/share/crypto-quant-nfi/freqtrade/.venv/bin/python" ]]; then
  # shellcheck disable=SC1091
  source "$HOME/.local/share/crypto-quant-nfi/freqtrade/.venv/bin/activate"
fi

mkdir -p "$PROJECT_ROOT/reports/decision_engine_v2" "$PROJECT_ROOT/user_data/decision_engine_v2"
exec python "$PROJECT_ROOT/scripts/calibrate_decision_engine_v2.py" "$@"
