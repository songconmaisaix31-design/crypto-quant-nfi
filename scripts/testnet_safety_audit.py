#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
TESTNET_CONFIG = PROJECT_ROOT / "user_data/config.testnet.local.json"
OUT = PROJECT_ROOT / "reports/testnet_run"
AUDIT = OUT / "testnet_safety_audit.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def contains_forbidden_endpoint(obj: Any) -> bool:
    text = json.dumps(obj, ensure_ascii=False).lower()
    return "fapi" in text or "dapi" in text or "futures" in text


def audit() -> dict[str, Any]:
    runtime = load_json(RUNTIME_CONFIG, {})
    testnet = load_json(TESTNET_CONFIG, {})
    rex = runtime.get("exchange", {})
    tex = testnet.get("exchange", {})
    endpoint_text = json.dumps(tex.get("ccxt_config", {}), ensure_ascii=False)
    checks = {
        "runtime_dry_run_true": runtime.get("dry_run") is True,
        "runtime_spot": runtime.get("trading_mode") == "spot",
        "runtime_margin_empty": runtime.get("margin_mode") in ("", None),
        "runtime_can_short_false": runtime.get("can_short") is False,
        "runtime_credentials_empty": not (rex.get("key") or rex.get("secret") or rex.get("password")),
        "testnet_config_exists": TESTNET_CONFIG.exists(),
        "testnet_config_isolated": TESTNET_CONFIG != RUNTIME_CONFIG,
        "testnet_spot": testnet.get("trading_mode") == "spot",
        "testnet_margin_empty": testnet.get("margin_mode") in ("", None),
        "testnet_can_short_false": testnet.get("can_short") is False,
        "testnet_credentials_not_written": not (tex.get("key") or tex.get("secret") or tex.get("password")),
        "testnet_endpoint": "testnet.binance.vision" in endpoint_text,
        "no_fapi_dapi_futures_endpoint": not contains_forbidden_endpoint(tex.get("ccxt_config", {})),
        "no_margin_short_leverage_enabled": testnet.get("margin_mode") in ("", None) and testnet.get("can_short") is False and not testnet.get("leverage"),
        "frequi_localhost": (testnet.get("api_server") or {}).get("listen_ip_address") == "127.0.0.1",
        "env_key_present": bool(os.environ.get("BINANCE_TESTNET_KEY")),
        "env_secret_present": bool(os.environ.get("BINANCE_TESTNET_SECRET")),
    }
    result = {
        "passed": all(v for k, v in checks.items() if k not in ("env_key_present", "env_secret_present")),
        "testnet_key_present": checks["env_key_present"] and checks["env_secret_present"],
        "checks": checks,
        "notes": "API key values are never written or printed.",
    }
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    result = audit()
    AUDIT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("TESTNET_SAFETY_AUDIT=" + ("PASS" if result["passed"] else "BLOCKED"))
    print("TESTNET_KEY_PRESENT=" + str(result["testnet_key_present"]))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
