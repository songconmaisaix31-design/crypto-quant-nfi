#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"
export PROJECT_ROOT

if [[ -f "${PROJECT_ROOT}/scripts/native-env.sh" ]]; then
  # shellcheck disable=SC1091
  source "${PROJECT_ROOT}/scripts/native-env.sh"
fi

PYTHON_BIN="${VENV_ROOT:-}/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

"${PYTHON_BIN}" "${PROJECT_ROOT}/scripts/shadow_signal_check.py"
