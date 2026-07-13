#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"
export PROJECT_ROOT

python3 - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["PROJECT_ROOT"])
template_path = root / "configs/config.testnet.template.json"
out_path = root / "user_data/config.testnet.local.json"
report_dir = root / "reports/testnet_run"
report_dir.mkdir(parents=True, exist_ok=True)

cfg = json.loads(template_path.read_text(encoding="utf-8"))
cfg["template_name"] = "binance_spot_testnet_local"
cfg["template_warning"] = "Local generated testnet config. It contains no API keys. Keys are read only from BINANCE_TESTNET_KEY and BINANCE_TESTNET_SECRET at runtime."
cfg["dry_run"] = False if (os.environ.get("BINANCE_TESTNET_KEY") and os.environ.get("BINANCE_TESTNET_SECRET")) else True
cfg["trading_mode"] = "spot"
cfg["margin_mode"] = ""
cfg["can_short"] = False
cfg["max_open_trades"] = 1
cfg["stake_amount"] = 10
cfg["db_url"] = "sqlite:///user_data/tradesv3.testnet.sqlite"
cfg["exchange"]["name"] = "binance"
cfg["exchange"]["key"] = ""
cfg["exchange"]["secret"] = ""
cfg["exchange"]["password"] = ""
cfg["exchange"]["ccxt_config"] = {
    "enableRateLimit": True,
    "urls": {
        "api": {
            "public": "https://testnet.binance.vision/api/v3",
            "private": "https://testnet.binance.vision/api/v3"
        }
    }
}
cfg["exchange"]["ccxt_async_config"] = cfg["exchange"]["ccxt_config"]
cfg["api_server"]["listen_ip_address"] = "127.0.0.1"
cfg["api_server"]["listen_port"] = 18080
cfg["internals"] = cfg.get("internals", {})
cfg["internals"]["process_throttle_secs"] = 5
cfg["testnet_safety"] = {
    "binance_spot_testnet_endpoint": "https://testnet.binance.vision/api/v3",
    "keys_source": "environment_only",
    "key_env": "BINANCE_TESTNET_KEY",
    "secret_env": "BINANCE_TESTNET_SECRET",
    "real_mainnet_keys_forbidden": True,
    "futures_margin_short_leverage_forbidden": True
}

out_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"[PASS] wrote {out_path}")
print(f"TESTNET_KEY_PRESENT={bool(os.environ.get('BINANCE_TESTNET_KEY') and os.environ.get('BINANCE_TESTNET_SECRET'))}")
PY

if ! grep -qxF "user_data/config.testnet.local.json" .gitignore; then
  printf "\nuser_data/config.testnet.local.json\n" >> .gitignore
  echo "[PASS] added user_data/config.testnet.local.json to .gitignore"
else
  echo "[PASS] user_data/config.testnet.local.json already ignored"
fi
