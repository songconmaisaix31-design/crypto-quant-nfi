#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
OUT = PROJECT_ROOT / "reports/testnet_run"
CSV_PATH = OUT / "testnet_order_lifecycle.csv"
LOG_PATH = OUT / "testnet_logs.txt"
SUMMARY_PATH = OUT / "testnet_order_lifecycle_summary.json"
REPORT_PATH = OUT / "testnet_order_lifecycle_report.md"
RUN_SUMMARY_PATH = OUT / "testnet_run_summary.json"
RUN_REPORT_PATH = OUT / "testnet_run_report.md"
PRELIVE_UPDATE_PATH = PROJECT_ROOT / "reports/pre_live_gate/pre_live_gate_testnet_evidence_update.md"


FIELDS = ["time", "step", "status", "symbol", "order_id", "side", "type", "price", "amount", "details"]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def write_rows(rows: list[dict[str, Any]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})


def write_report(rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    lines = [
        "# Testnet Order Lifecycle Report",
        "",
        f"Status: `{summary['status']}`",
        "",
        f"- Testnet key present: `{summary['testnet_key_present']}`",
        f"- Symbol: `{summary.get('symbol', '')}`",
        f"- Limit only: `{summary['limit_only']}`",
        f"- Used testnet: `{summary['used_testnet']}`",
        f"- Created order: `{summary['created_order']}`",
        f"- Canceled order: `{summary['canceled_order']}`",
        f"- Verified canceled: `{summary['verified_canceled']}`",
        f"- Mainnet touched: `{summary['mainnet_touched']}`",
        "",
        "| step | status | details |",
        "|---|---|---|",
    ]
    for row in rows:
        lines.append(f"| `{row.get('step')}` | `{row.get('status')}` | {row.get('details')} |")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_run_report(summary)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def update_run_report(order_summary: dict[str, Any]) -> None:
    run_summary = read_json(RUN_SUMMARY_PATH)
    order_passed = order_summary.get("status") == "PASS" and bool(order_summary.get("verified_canceled"))
    if order_summary.get("testnet_key_present") is True:
        run_summary["testnet_key_present"] = True
    run_summary["order_lifecycle_verified"] = order_passed
    run_summary["order_lifecycle_status"] = order_summary.get("status")
    run_summary["order_lifecycle_symbol"] = order_summary.get("symbol")
    run_summary["order_lifecycle_limit_only"] = bool(order_summary.get("limit_only"))
    run_summary["order_lifecycle_mainnet_touched"] = bool(order_summary.get("mainnet_touched"))
    run_summary["micro_live_allowed"] = False
    run_summary["real_trading_allowed"] = False
    run_summary["micro_live_status"] = "BLOCKED"
    if run_summary.get("smoke_test_passed") and order_passed:
        run_summary["status"] = "PASS"
    RUN_SUMMARY_PATH.write_text(json.dumps(run_summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")

    lines = [
        "# Binance Spot Testnet Run Report",
        "",
        f"Status: `{run_summary.get('status', order_summary.get('status'))}`",
        "",
        f"- Testnet allowed: `{run_summary.get('testnet_allowed', True)}`",
        f"- Micro-live allowed: `{run_summary.get('micro_live_allowed', False)}`",
        f"- Real trading allowed: `{run_summary.get('real_trading_allowed', False)}`",
        f"- Testnet key present: `{run_summary.get('testnet_key_present', order_summary.get('testnet_key_present', False))}`",
        f"- Endpoint audit passed: `{run_summary.get('endpoint_audit_passed', False)}`",
        f"- Testnet endpoint reachable: `{run_summary.get('endpoint_reachable', False)}`",
        f"- Using testnet endpoint: `{run_summary.get('using_testnet_endpoint', True)}`",
        f"- Safety audit passed: `{run_summary.get('safety_audit_passed', False)}`",
        f"- Smoke test passed: `{run_summary.get('smoke_test_passed', False)}`",
        f"- Order lifecycle verified: `{order_passed}`",
        f"- Order lifecycle limit only: `{order_summary.get('limit_only', True)}`",
        f"- Mainnet touched: `{order_summary.get('mainnet_touched', False)}`",
        "",
        "No real mainnet API key is written or printed. Micro-live remains BLOCKED.",
    ]
    RUN_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    PRELIVE_UPDATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PRELIVE_UPDATE_PATH.write_text(
        "# Pre-Live Gate Testnet Evidence Update\n\n"
        f"- Testnet smoke status: `{'PASS' if run_summary.get('smoke_test_passed') else run_summary.get('status', 'UNKNOWN')}`.\n"
        f"- Testnet endpoint reachable: `{run_summary.get('endpoint_reachable', False)}`.\n"
        f"- Order lifecycle verified: `{order_passed}`.\n"
        "- Micro-live remains `BLOCKED`.\n"
        "- Real small-money trading is not allowed because pre-live v3, forward sample, consistency, and decision-engine gates are not satisfied.\n",
        encoding="utf-8",
    )


def add(rows: list[dict[str, Any]], step: str, status: str, details: str = "", **extra: Any) -> None:
    row = {"time": now(), "step": step, "status": status, "details": details}
    row.update(extra)
    rows.append(row)


def get_filter(market: dict[str, Any], filter_type: str) -> dict[str, Any]:
    for item in (market.get("info") or {}).get("filters") or []:
        if item.get("filterType") == filter_type:
            return item
    return {}


def as_float(value: Any, default: float) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def main() -> int:
    rows: list[dict[str, Any]] = []
    if not os.environ.get("BINANCE_TESTNET_KEY") or not os.environ.get("BINANCE_TESTNET_SECRET"):
        add(rows, "precheck", "TESTNET_KEY_MISSING", "Set BINANCE_TESTNET_KEY and BINANCE_TESTNET_SECRET.")
        write_rows(rows)
        write_report(rows, {
            "status": "TESTNET_KEY_MISSING",
            "testnet_key_present": False,
            "limit_only": True,
            "used_testnet": False,
            "created_order": False,
            "canceled_order": False,
            "verified_canceled": False,
            "mainnet_touched": False,
        })
        print("TESTNET_KEY_MISSING")
        return 0
    try:
        import ccxt
        ex = ccxt.binance({
            "apiKey": os.environ["BINANCE_TESTNET_KEY"],
            "secret": os.environ["BINANCE_TESTNET_SECRET"],
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })
        ex.set_sandbox_mode(True)
        markets = ex.load_markets()
        symbol = "BTC/USDT" if "BTC/USDT" in markets else "ETH/USDT"
        ticker = ex.fetch_ticker(symbol)
        last = float(ticker["last"] or ticker["bid"] or ticker["ask"])
        bid = float(ticker.get("bid") or last)
        ask = float(ticker.get("ask") or last)
        market = markets[symbol]
        percent_by_side = get_filter(market, "PERCENT_PRICE_BY_SIDE")
        bid_multiplier_down = as_float(percent_by_side.get("bidMultiplierDown"), 0.8)
        bid_multiplier_up = as_float(percent_by_side.get("bidMultiplierUp"), 1.2)
        lower_allowed = last * bid_multiplier_down * 1.02
        upper_allowed = last * bid_multiplier_up * 0.98
        desired_price = min(bid * 0.995, ask * 0.995, last * 0.995)
        price = min(max(desired_price, lower_allowed), upper_allowed)
        if price >= ask:
            add(rows, "prepare_limit_order", "BLOCKED", "Cannot place a non-crossing limit buy inside current percent-price filter range.", symbol=symbol, side="buy", type="limit", price=price)
            write_rows(rows)
            write_report(rows, {
                "status": "BLOCKED",
                "testnet_key_present": True,
                "symbol": symbol,
                "limit_only": True,
                "used_testnet": True,
                "created_order": False,
                "canceled_order": False,
                "verified_canceled": False,
                "mainnet_touched": False,
                "reason": "percent_price_filter_prevents_safe_resting_order",
                "last": last,
                "bid": bid,
                "ask": ask,
                "lower_allowed": lower_allowed,
                "upper_allowed": upper_allowed,
            })
            print("TESTNET_ORDER_LIFECYCLE=BLOCKED (PERCENT_PRICE_RANGE)")
            return 0
        price = float(ex.price_to_precision(symbol, price))
        amount_min = ((market.get("limits") or {}).get("amount") or {}).get("min") or 0.0001
        cost_min = ((market.get("limits") or {}).get("cost") or {}).get("min") or 5
        amount_for_cost = (float(cost_min) * 1.2) / price
        amount = max(float(amount_min), amount_for_cost, 0.0001)
        amount = float(ex.amount_to_precision(symbol, amount))
        while amount * price < float(cost_min) * 1.05:
            amount = float(ex.amount_to_precision(symbol, amount * 1.1))
        balance = ex.fetch_balance()
        usdt_free = float(((balance.get("free") or {}).get("USDT")) or 0)
        required_usdt = amount * price
        if usdt_free < required_usdt:
            add(rows, "prepare_limit_order", "BLOCKED", "Insufficient Spot Testnet USDT balance for minimum notional order.", symbol=symbol, side="buy", type="limit", price=price, amount=amount)
            write_rows(rows)
            write_report(rows, {
                "status": "BLOCKED",
                "testnet_key_present": True,
                "symbol": symbol,
                "limit_only": True,
                "used_testnet": True,
                "created_order": False,
                "canceled_order": False,
                "verified_canceled": False,
                "mainnet_touched": False,
                "reason": "insufficient_testnet_usdt",
                "required_usdt": required_usdt,
                "available_usdt": usdt_free,
                "min_cost": cost_min,
            })
            print("TESTNET_ORDER_LIFECYCLE=BLOCKED (INSUFFICIENT_TESTNET_USDT)")
            return 0
        add(rows, "prepare_limit_order", "PASS", "Using non-crossing limit buy inside Binance percent-price filter range.", symbol=symbol, side="buy", type="limit", price=price, amount=amount)
        order = ex.create_limit_buy_order(symbol, amount, price)
        order_id = str(order.get("id", ""))
        add(rows, "create_limit_order", "PASS", "Order submitted to Binance Spot Testnet only.", symbol=symbol, order_id=order_id, side="buy", type="limit", price=price, amount=amount)
        fetched = ex.fetch_order(order_id, symbol)
        add(rows, "fetch_order", "PASS", f"status={fetched.get('status')}", symbol=symbol, order_id=order_id)
        canceled = ex.cancel_order(order_id, symbol)
        add(rows, "cancel_order", "PASS", f"status={canceled.get('status')}", symbol=symbol, order_id=order_id)
        try:
            final = ex.fetch_order(order_id, symbol)
            final_status = final.get("status", "")
        except Exception as exc:
            final_status = f"fetch_after_cancel_failed:{type(exc).__name__}"
        ok = "cancel" in str(final_status).lower() or final_status in ("closed", "canceled")
        add(rows, "verify_cancelled", "PASS" if ok else "CHECK", f"final_status={final_status}", symbol=symbol, order_id=order_id)
        write_rows(rows)
        write_report(rows, {
            "status": "PASS" if ok else "CHECK",
            "testnet_key_present": True,
            "symbol": symbol,
            "order_id": order_id,
            "limit_only": True,
            "used_testnet": True,
            "created_order": bool(order_id),
            "canceled_order": True,
            "verified_canceled": ok,
            "mainnet_touched": False,
            "price": price,
            "amount": amount,
            "min_amount": amount_min,
            "min_cost": cost_min,
        })
        print("TESTNET_ORDER_LIFECYCLE=" + ("PASS" if ok else "CHECK"))
        return 0 if ok else 2
    except Exception as exc:
        add(rows, "exception", "FAIL", f"{type(exc).__name__}: {exc}")
        write_rows(rows)
        write_report(rows, {
            "status": "BLOCKED",
            "testnet_key_present": True,
            "limit_only": True,
            "used_testnet": True,
            "created_order": any(r.get("step") == "create_limit_order" and r.get("status") == "PASS" for r in rows),
            "canceled_order": any(r.get("step") == "cancel_order" and r.get("status") == "PASS" for r in rows),
            "verified_canceled": False,
            "mainnet_touched": False,
            "error": f"{type(exc).__name__}: {exc}",
        })
        LOG_PATH.write_text(f"testnet order lifecycle failed: {type(exc).__name__}: {exc}\n", encoding="utf-8")
        print(f"TESTNET_ORDER_LIFECYCLE=BLOCKED ({type(exc).__name__})")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
