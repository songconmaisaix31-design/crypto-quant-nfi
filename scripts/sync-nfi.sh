#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/native-env.sh"

mkdir -p "$PROJECT_ROOT/user_data/strategies"
src="$NFI_ROOT/$STRATEGY_NAME.py"
dst="$PROJECT_ROOT/user_data/strategies/$STRATEGY_NAME.py"
[[ -f "$src" ]] || die "NFI strategy not found: $src"

ln -sfn "$src" "$dst" 2>/dev/null || cp "$src" "$dst"
if [[ -L "$dst" ]]; then
  echo "[PASS] Strategy symlinked: $dst -> $(readlink "$dst")"
else
  echo "[PASS] Strategy copied: $dst"
fi

