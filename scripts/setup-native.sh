#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/native-env.sh"

mkdir -p "$RUNTIME_ROOT" "$FREQTRADE_ROOT" \
  "$PROJECT_ROOT/user_data/strategies" "$PROJECT_ROOT/user_data/data" \
  "$PROJECT_ROOT/user_data/logs" "$PROJECT_ROOT/user_data/backtest_results"

if [[ ! -x "$VENV_ROOT/bin/freqtrade" ]]; then
  die "Freqtrade venv missing. Bootstrap it with: python3 -m venv --without-pip '$VENV_ROOT' and install freqtrade."
fi

"$(dirname "$0")/sync-nfi.sh"

python3 - "$PROJECT_ROOT/user_data/config.json" "$CONFIG_PATH" <<'PY'
import json, pathlib, sys
src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
base = json.load(src.open(encoding="utf-8")) if src.exists() else {}
cfg = {
    "$schema": "https://schema.freqtrade.io/schema.json",
    "bot_name": "crypto_quant_nfi_native_dry_run",
    "initial_state": "running",
    "max_open_trades": 6,
    "stake_currency": "USDT",
    "stake_amount": 100,
    "tradable_balance_ratio": 0.99,
    "fiat_display_currency": "USD",
    "dry_run": True,
    "dry_run_wallet": 10000,
    "cancel_open_orders_on_exit": False,
    "trading_mode": "spot",
    "margin_mode": "",
    "timeframe": "5m",
    "strategy": "NostalgiaForInfinityX7",
    "can_short": False,
    "use_exit_signal": True,
    "exit_profit_only": False,
    "ignore_roi_if_entry_signal": True,
    "unfilledtimeout": base.get("unfilledtimeout", {"entry": 10, "exit": 10, "exit_timeout_count": 0, "unit": "minutes"}),
    "entry_pricing": base.get("entry_pricing", {"price_side": "same", "use_order_book": True, "order_book_top": 1}),
    "exit_pricing": base.get("exit_pricing", {"price_side": "same", "use_order_book": True, "order_book_top": 1}),
    "exchange": {
        "name": base.get("exchange", {}).get("name", "binance"),
        "key": "",
        "secret": "",
        "ccxt_config": {"enableRateLimit": True, "timeout": 60000},
        "ccxt_async_config": {"enableRateLimit": True, "timeout": 60000},
        "pair_whitelist": [
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT",
        ],
        "pair_blacklist": [
            ".*(BULL|BEAR|UP|DOWN|3L|3S|5L|5S)/.*",
            ".*(USDC|BUSD|TUSD|FDUSD|DAI|PAX|USD)/USDT",
        ],
    },
    "pairlists": [{"method": "StaticPairList"}],
    "telegram": {"enabled": False, "token": "", "chat_id": ""},
    "api_server": {
        "enabled": True,
        "listen_ip_address": "127.0.0.1",
        "listen_port": 8080,
        "verbosity": "error",
        "enable_openapi": False,
        "jwt_secret_key": "override-from-env",
        "ws_token": "override-from-env",
        "CORS_origins": [],
        "username": "override-from-env",
        "password": "override-from-env",
    },
    "internals": {"process_throttle_secs": 5},
}
dst.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
print(f"[PASS] Wrote {dst}")
PY

python3 - "$NFI_ROOT/$STRATEGY_NAME.py" "$PROJECT_ROOT/user_data/runtime-timeframes.txt" <<'PY'
import ast, pathlib, re, sys
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
frames = []
for name in ("timeframe", "info_timeframes", "btc_info_timeframes"):
    m = re.search(rf"^\s*{name}\s*=\s*(.+)$", text, re.M)
    if not m:
        continue
    try:
        val = ast.literal_eval(m.group(1).strip())
    except Exception:
        continue
    if isinstance(val, str):
        frames.append(val)
    else:
        frames.extend(str(x) for x in val)
order = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"]
frames = sorted(set(frames), key=lambda x: order.index(x) if x in order else 999)
pathlib.Path(sys.argv[2]).write_text("\n".join(frames) + "\n", encoding="utf-8")
print("[PASS] Timeframes: " + " ".join(frames))
PY

ensure_native_safety
freqtrade_native --version

if systemctl --user status >/dev/null 2>&1; then
  mkdir -p "$HOME/.config/systemd/user"
  cat > "$HOME/.config/systemd/user/crypto-quant-nfi.service" <<EOF
[Unit]
Description=crypto-quant-nfi Freqtrade dry-run
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_ROOT
ExecStart=$PROJECT_ROOT/scripts/run-native.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  echo "[PASS] Wrote systemd user service: $HOME/.config/systemd/user/crypto-quant-nfi.service"
else
  echo "[INFO] systemd user service is unavailable; scripts will use nohup fallback"
fi
