#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"
export PROJECT_ROOT

REPORT_DIR="$PROJECT_ROOT/reports/testnet_run"
mkdir -p "$REPORT_DIR"
LOG_FILE="$REPORT_DIR/testnet_logs.txt"
PYTHON_BIN="python3"
if [[ -x "$HOME/.local/share/crypto-quant-nfi/freqtrade/.venv/bin/python" ]]; then
  PYTHON_BIN="$HOME/.local/share/crypto-quant-nfi/freqtrade/.venv/bin/python"
fi

{
  echo "=== testnet smoke test $(date -Is) ==="
  bash scripts/build-testnet-config.sh
  python3 scripts/testnet_endpoint_audit.py
  python3 scripts/testnet_safety_audit.py
  "$PYTHON_BIN" - <<'PY'
import json
import os
import sys
from pathlib import Path

root = Path(os.environ["PROJECT_ROOT"])
out = root / "reports/testnet_run/testnet_smoke_summary.json"
smoke_json = root / "reports/testnet_run/testnet_smoke_test_result.json"
smoke_md = root / "reports/testnet_run/testnet_smoke_test_result.md"
run_summary = root / "reports/testnet_run/testnet_run_summary.json"
run_report = root / "reports/testnet_run/testnet_run_report.md"
prelive_update = root / "reports/pre_live_gate/pre_live_gate_testnet_evidence_update.md"
audit_path = root / "reports/testnet_run/testnet_safety_audit.json"
result = {
    "testnet_key_present": bool(os.environ.get("BINANCE_TESTNET_KEY") and os.environ.get("BINANCE_TESTNET_SECRET")),
    "endpoint": "https://testnet.binance.vision/api/v3",
    "endpoint_reachable": False,
    "markets_checked": False,
    "balance_checked": False,
    "symbol_filters_checked": False,
    "notes": []
}
if result["testnet_key_present"]:
  try:
    import ccxt
    ex = ccxt.binance({
        "apiKey": os.environ["BINANCE_TESTNET_KEY"],
        "secret": os.environ["BINANCE_TESTNET_SECRET"],
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    ex.set_sandbox_mode(True)
    server_time = ex.public_get_time()
    result["endpoint_reachable"] = isinstance(server_time, dict) and bool(server_time.get("serverTime"))
    result["server_time_checked"] = result["endpoint_reachable"]
    result["server_time_response_present"] = result["endpoint_reachable"]
    markets = ex.load_markets()
    result["markets_checked"] = "BTC/USDT" in markets
    result["exchange_info_checked"] = result["markets_checked"]
    bal = ex.fetch_balance()
    result["balance_checked"] = isinstance(bal, dict)
    market = markets.get("BTC/USDT") or {}
    result["symbol_filters_checked"] = bool(market.get("limits") or market.get("precision"))
    result["btc_usdt_limits"] = market.get("limits", {})
    result["btc_usdt_precision"] = market.get("precision", {})
    result["min_amount"] = ((market.get("limits") or {}).get("amount") or {}).get("min")
    result["min_cost"] = ((market.get("limits") or {}).get("cost") or {}).get("min")
  except Exception as exc:
    result["notes"].append(f"ccxt check failed: {type(exc).__name__}: {exc}")
else:
    try:
        import json as _json
        import urllib.request
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("https://testnet.binance.vision/api/v3/time", timeout=15) as resp:
            payload = _json.loads(resp.read().decode("utf-8"))
            result["endpoint_reachable"] = resp.status == 200
            result["server_time_checked"] = resp.status == 200 and bool(payload.get("serverTime"))
            result["server_time_response_present"] = result["server_time_checked"]
    except Exception as exc:
        result["notes"].append(f"endpoint check failed: {type(exc).__name__}: {exc}")
    result["notes"].append("TESTNET_KEY_MISSING: Set BINANCE_TESTNET_KEY and BINANCE_TESTNET_SECRET.")
out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
smoke_json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {}
order_csv = root / "reports/testnet_run/testnet_order_lifecycle.csv"
order_done = False
if order_csv.exists():
    text = order_csv.read_text(encoding="utf-8", errors="ignore")
    order_done = "verify_cancelled" in text and "PASS" in text
status = "TESTNET_KEY_MISSING" if not result["testnet_key_present"] else ("PASS" if result["endpoint_reachable"] and result["markets_checked"] and result["balance_checked"] else "CHECK_FAILED")
summary = {
    "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"),
    "status": status,
    "testnet_allowed": True,
    "micro_live_allowed": False,
    "real_trading_allowed": False,
    "testnet_key_present": result["testnet_key_present"],
    "endpoint_reachable": result["endpoint_reachable"],
    "endpoint_audit_passed": (root / "reports/testnet_run/testnet_endpoint_audit.json").exists() and json.loads((root / "reports/testnet_run/testnet_endpoint_audit.json").read_text()).get("passed", False),
    "smoke_test_passed": status == "PASS",
    "using_testnet_endpoint": "testnet.binance.vision" in result["endpoint"],
    "safety_audit_passed": audit.get("passed", False),
    "order_lifecycle_verified": order_done,
    "micro_live_status": "BLOCKED",
    "notes": result["notes"],
}
run_summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
lines = [
    "# Binance Spot Testnet Run Report",
    "",
    f"Status: `{status}`",
    "",
    f"- Testnet allowed: `{summary['testnet_allowed']}`",
    f"- Micro-live allowed: `{summary['micro_live_allowed']}`",
    f"- Real trading allowed: `{summary['real_trading_allowed']}`",
    f"- Testnet key present: `{summary['testnet_key_present']}`",
    f"- Endpoint audit passed: `{summary['endpoint_audit_passed']}`",
    f"- Testnet endpoint reachable: `{summary['endpoint_reachable']}`",
    f"- Using testnet endpoint: `{summary['using_testnet_endpoint']}`",
    f"- Safety audit passed: `{summary['safety_audit_passed']}`",
    f"- Order lifecycle verified: `{summary['order_lifecycle_verified']}`",
    "",
    "No real mainnet API key is written or printed. Micro-live remains BLOCKED.",
]
run_report.write_text("\n".join(lines) + "\n", encoding="utf-8")
smoke_lines = [
    "# Testnet Smoke Test Result",
    "",
    f"Status: `{status}`",
    "",
    f"- Testnet key present: `{result['testnet_key_present']}`",
    f"- Server time readable: `{result.get('server_time_checked', False)}`",
    f"- exchangeInfo/markets readable: `{result.get('exchange_info_checked', False)}`",
    f"- Account balance readable: `{result['balance_checked']}`",
    f"- Symbol filters readable: `{result['symbol_filters_checked']}`",
    f"- Min amount: `{result.get('min_amount')}`",
    f"- Min cost: `{result.get('min_cost')}`",
    "",
    "API key values are not printed or written.",
]
smoke_md.write_text("\n".join(smoke_lines) + "\n", encoding="utf-8")
prelive_update.parent.mkdir(parents=True, exist_ok=True)
prelive_update.write_text(
    "# Pre-Live Gate Testnet Evidence Update\n\n"
    f"- Testnet smoke status: `{status}`.\n"
    f"- Testnet endpoint reachable: `{summary['endpoint_reachable']}`.\n"
    f"- Order lifecycle verified: `{summary['order_lifecycle_verified']}`.\n"
    "- Micro-live remains `BLOCKED`.\n"
    "- Real small-money trading is not allowed because pre-live v3, forward sample, consistency, and decision-engine gates are not satisfied.\n",
    encoding="utf-8",
)
print("TESTNET_SMOKE_STATUS=" + status)
print("TESTNET_KEY_PRESENT=" + str(result["testnet_key_present"]))
PY
} 2>&1 | tee -a "$LOG_FILE"
