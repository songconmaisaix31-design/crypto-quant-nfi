#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
TESTNET_CONFIG = PROJECT_ROOT / "user_data/config.testnet.local.json"
OUT = PROJECT_ROOT / "reports/testnet_run"
JSON_OUT = OUT / "testnet_endpoint_audit.json"
MD_OUT = OUT / "testnet_endpoint_audit.md"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def flatten_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str):
        urls.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            urls.extend(flatten_urls(v))
    elif isinstance(value, list):
        for v in value:
            urls.extend(flatten_urls(v))
    return urls


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_json(TESTNET_CONFIG, {})
    ex = cfg.get("exchange", {})
    ccxt_config = ex.get("ccxt_config", {})
    urls = flatten_urls(ccxt_config.get("urls", {}))
    text = json.dumps(ccxt_config, ensure_ascii=False).lower()
    expected_paths = ["/api/v3/time", "/api/v3/exchangeInfo", "/api/v3/account", "/api/v3/order"]
    endpoint_base_ok = any("https://testnet.binance.vision/api/v3" in u for u in urls)
    checks = {
        "config_exists": TESTNET_CONFIG.exists(),
        "endpoint_base_testnet": endpoint_base_ok,
        "expected_paths": expected_paths,
        "no_double_v3": "/api/v3/v3" not in text,
        "no_mainnet_api_binance_com": "api.binance.com" not in text,
        "no_fapi": "fapi" not in text,
        "no_dapi": "dapi" not in text,
        "no_sapi": "sapi" not in text,
        "spot_only": cfg.get("trading_mode") == "spot",
        "margin_empty": cfg.get("margin_mode") in ("", None),
        "can_short_false": cfg.get("can_short") is False,
        "credentials_not_written": not (ex.get("key") or ex.get("secret") or ex.get("password")),
    }
    passed = all(checks.values())
    result = {
        "generated_at": now(),
        "passed": passed,
        "endpoint_urls": urls,
        "final_requests_expected": {
            "time": "https://testnet.binance.vision/api/v3/time",
            "exchangeInfo": "https://testnet.binance.vision/api/v3/exchangeInfo",
            "account": "https://testnet.binance.vision/api/v3/account",
            "order": "https://testnet.binance.vision/api/v3/order",
        },
        "checks": checks,
        "notes": "Audit only. No API keys are printed or written.",
    }
    JSON_OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# Testnet Endpoint Audit",
        "",
        f"Generated: `{result['generated_at']}`",
        "",
        f"Result: `{'PASS' if passed else 'BLOCKED'}`",
        "",
        "## Expected Requests",
        "- `https://testnet.binance.vision/api/v3/time`",
        "- `https://testnet.binance.vision/api/v3/exchangeInfo`",
        "- `https://testnet.binance.vision/api/v3/account`",
        "- `https://testnet.binance.vision/api/v3/order`",
        "",
        "## Checks",
        "| check | status |",
        "|---|---|",
    ]
    for key, value in checks.items():
        lines.append(f"| `{key}` | `{'PASS' if value else 'FAIL'}` |")
    MD_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("TESTNET_ENDPOINT_AUDIT=" + ("PASS" if passed else "BLOCKED"))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
