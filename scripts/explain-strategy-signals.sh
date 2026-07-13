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

if ! command -v python >/dev/null 2>&1; then
  echo "[FAIL] python not found. Activate the Freqtrade virtualenv first." >&2
  exit 1
fi

mkdir -p "$PROJECT_ROOT/reports/strategy_explain"
exec python "$PROJECT_ROOT/scripts/explain_strategy_signals.py" "$@"
