#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/native-env.sh"

ensure_native_safety
freqtrade_native list-strategies --config "$CONFIG_PATH" --userdir "$PROJECT_ROOT/user_data" --strategy-path "$PROJECT_ROOT/user_data/strategies" \
  | tee "$PROJECT_ROOT/user_data/logs/validate-native-list-strategies.log" \
  | grep -q "$STRATEGY_NAME"
echo "[PASS] Strategy loadable: $STRATEGY_NAME"

freqtrade_native show-config --config "$CONFIG_PATH" --userdir "$PROJECT_ROOT/user_data" >/tmp/crypto-quant-nfi-show-config.txt
grep -q "dry_run" /tmp/crypto-quant-nfi-show-config.txt || die "show-config did not run correctly"
echo "[PASS] Config resolved"

exchange="$(json_get exchange.name)"
if freqtrade_native list-markets --config "$CONFIG_PATH" --userdir "$PROJECT_ROOT/user_data" --quote USDT --print-list >/tmp/crypto-quant-nfi-markets.txt 2>"$PROJECT_ROOT/user_data/logs/list-markets-${exchange}.err"; then
  echo "[PASS] Public exchange markets reachable: $exchange"
else
  echo "[FAIL] Public exchange markets unreachable: $exchange" >&2
  echo "[FAIL] See $PROJECT_ROOT/user_data/logs/list-markets-${exchange}.err" >&2
  exit 1
fi

python3 - "$CONFIG_PATH" /tmp/crypto-quant-nfi-markets.txt <<'PY'
import json, re, sys
cfg_path, markets_path = sys.argv[1:]
cfg = json.load(open(cfg_path, encoding="utf-8"))
text = open(markets_path, encoding="utf-8", errors="ignore").read()
existing = set(re.findall(r"[A-Z0-9]+/USDT(?::USDT)?", text))
pairs = [p for p in cfg["exchange"]["pair_whitelist"] if p in existing or not existing]
if not pairs:
    raise SystemExit("No configured pairs were found in exchange markets output")
cfg["exchange"]["pair_whitelist"] = pairs
json.dump(cfg, open(cfg_path, "w", encoding="utf-8"), indent=2)
print("[PASS] Pair whitelist: " + " ".join(pairs))
PY
