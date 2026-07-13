#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

strategy="$(strategy_name)"
exchange="$(python3 - "$CONFIG_FILE" <<'PY'
import json, sys
cfg=json.load(open(sys.argv[1], encoding="utf-8"))
print(cfg.get("exchange", {}).get("name", "unknown"))
PY
)"
dry="$(python3 - "$CONFIG_FILE" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("dry_run"))
PY
)"

echo "Container status:"
compose ps || true
echo
echo "Freqtrade version:"
if docker image inspect freqtradeorg/freqtrade:stable >/dev/null 2>&1; then
  compose run --rm --no-deps freqtrade --version || true
else
  echo "freqtradeorg/freqtrade:stable image is not available locally. Run: docker pull freqtradeorg/freqtrade:stable"
fi
echo
echo "NFI commit:"
git -C "$NFI_DIR" rev-parse HEAD || true
echo
echo "Strategy: $strategy"
echo "Exchange: $exchange"
echo "Dry-run: $dry"
echo "Web UI: http://127.0.0.1:${FREQTRADE__API_SERVER__LISTEN_PORT:-8080}"
