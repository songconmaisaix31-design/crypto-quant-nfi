#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"
export PROJECT_ROOT

PYTHON_BIN="python3"
if [[ -x "$HOME/.local/share/crypto-quant-nfi/freqtrade/.venv/bin/python" ]]; then
  PYTHON_BIN="$HOME/.local/share/crypto-quant-nfi/freqtrade/.venv/bin/python"
fi

"$PYTHON_BIN" scripts/testnet_order_lifecycle_check.py
