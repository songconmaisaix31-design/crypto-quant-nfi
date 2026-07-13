#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import zipfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
REPORT_DIR = PROJECT_ROOT / "reports/pre_live_gate"
REPORT_MD = REPORT_DIR / "pre_live_gate_report.md"
SUMMARY_JSON = REPORT_DIR / "pre_live_gate_summary.json"
MATRIX_CSV = REPORT_DIR / "pre_live_gate_matrix.csv"
LOG_TXT = REPORT_DIR / "pre_live_gate_logs.txt"
BLOCK_TXT = REPORT_DIR / "LIVE_TRADING_BLOCKED.txt"
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
SAMPLE_SUMMARY = PROJECT_ROOT / "reports/sample_validation/sample_validation_summary.json"
STRATEGY_SUMMARY = PROJECT_ROOT / "reports/strategy_explain/strategy_explain_summary.json"
DRYRUN_DB = PROJECT_ROOT / "user_data/tradesv3.dryrun.sqlite"
DRYRUN_LOG = PROJECT_ROOT / "user_data/logs/freqtrade-native.log"
STABILITY_LOG = PROJECT_ROOT / "user_data/logs/network-repair/dry-run-stability.log"
PRIMARY_EXPORT = PROJECT_ROOT / "reports/sample_validation/exports/expanded_365d"
SLIPPAGE_PER_SIDE = 0.0005
MIN_DRY_RUN_DAYS = 14
MAX_DRY_RUN_DAYS_TARGET = 28


class Recorder:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def log(self, line: str = "") -> None:
        self.lines.append(line)
        print(line)

    def section(self, title: str) -> None:
        self.log(f"\n=== {title} ===")

    def write(self) -> None:
        LOG_TXT.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def latest_zip(path: Path) -> Path | None:
    zips = sorted(path.glob("*.zip"), key=lambda p: p.stat().st_mtime)
    return zips[-1] if zips else None


def read_backtest_export() -> dict[str, Any]:
    zip_path = latest_zip(PRIMARY_EXPORT)
    if not zip_path:
        return {}
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith(".json") and "_config" not in name and "_meta" not in name:
                data = json.loads(zf.read(name).decode("utf-8"))
                strat = data.get("strategy", {}).get("NostalgiaForInfinityX7", {})
                strat["_zip_path"] = str(zip_path)
                return strat
    return {}


def safety_check() -> dict[str, Any]:
    cfg = load_json(RUNTIME_CONFIG, {})
    ex = cfg.get("exchange", {})
    api = cfg.get("api_server", {})
    checks = {
        "dry_run": cfg.get("dry_run") is True,
        "trading_mode_spot": cfg.get("trading_mode") == "spot",
        "margin_mode_empty": cfg.get("margin_mode") in ("", None),
        "can_short_false": cfg.get("can_short") is False,
        "exchange_credentials_empty": not (ex.get("key") or ex.get("secret") or ex.get("password")),
        "api_localhost": api.get("listen_ip_address") == "127.0.0.1",
    }
    risky_terms_enabled = []
    if cfg.get("trading_mode") not in ("spot", None):
        risky_terms_enabled.append(f"trading_mode={cfg.get('trading_mode')}")
    if cfg.get("margin_mode") not in ("", None):
        risky_terms_enabled.append(f"margin_mode={cfg.get('margin_mode')}")
    if cfg.get("can_short") is True:
        risky_terms_enabled.append("can_short=True")
    return {"checks": checks, "risky_terms_enabled": risky_terms_enabled, "pass": all(checks.values()) and not risky_terms_enabled}


def sample_gate(sample: dict[str, Any], bt: dict[str, Any]) -> dict[str, Any]:
    best = None
    for row in sample.get("groups", []):
        days = int(row.get("days") or 0)
        trades = int(row.get("trades_count") or 0)
        if days >= 365 and 50 <= trades <= 100:
            best = row
            break
    if not best and bt:
        days = int(bt.get("backtest_days") or 0)
        trades = int(bt.get("total_trades") or 0)
        if days >= 365 and 50 <= trades <= 100:
            best = {"group": "expanded_365d_export", "days": days, "trades_count": trades, "timerange": bt.get("timerange")}
    return {
        "pass": bool(best),
        "evidence": best or {},
        "message": "Found 365d backtest with 50-100 trades." if best else "No 365d backtest with 50-100 trades found.",
    }


def market_state_gate(strategy: dict[str, Any]) -> dict[str, Any]:
    regimes = strategy.get("market_regime_counts", {}) if isinstance(strategy, dict) else {}
    covered = {
        "up": bool(regimes.get("trend_up", 0)),
        "down": bool(regimes.get("trend_down", 0)),
        "range": bool(regimes.get("rangebound_or_compression", 0) or regimes.get("mixed", 0)),
        "panic": bool(regimes.get("fast_drop_rebound", 0) or regimes.get("trend_down", 0)),
        "greed": False,
    }
    return {
        "pass": all(covered.values()),
        "covered": covered,
        "regime_counts": regimes,
        "message": "All required market states covered." if all(covered.values()) else "Missing one or more required market states.",
    }


def fee_slippage_gate(bt: dict[str, Any]) -> dict[str, Any]:
    trades = bt.get("trades", []) if isinstance(bt, dict) else []
    fee_seen = bool(trades) and all(float(t.get("fee_open", 0) or 0) > 0 and float(t.get("fee_close", 0) or 0) > 0 for t in trades)
    gross_profit = float(bt.get("profit_total", 0) or 0)
    stress_cost = len(trades) * (SLIPPAGE_PER_SIDE * 2)
    stressed_profit = gross_profit - stress_cost
    return {
        "pass": fee_seen and bool(trades),
        "fee_included": fee_seen,
        "slippage_model": f"{SLIPPAGE_PER_SIDE * 100:.3f}% per side read-only stress estimate",
        "trades": len(trades),
        "profit_total_before_slippage": round(gross_profit, 8),
        "profit_total_after_slippage_estimate": round(stressed_profit, 8),
        "message": "Fee evidence found and slippage stress estimate generated." if fee_seen else "Fee/slippage evidence incomplete.",
    }


def decision_engine_gate() -> dict[str, Any]:
    candidates = [
        PROJECT_ROOT / "reports/decision_engine",
        PROJECT_ROOT / "reports/decision_engine_summary.json",
        PROJECT_ROOT / "reports/decision_engine_filter_report.md",
    ]
    exists = [str(p) for p in candidates if p.exists()]
    return {
        "pass": False,
        "evidence_files": exists,
        "message": "Decision-engine drawdown reduction and false-kill evidence is not available; live trading remains blocked.",
    }


def dry_run_span() -> dict[str, Any]:
    spans = []
    if DRYRUN_DB.exists():
        try:
            con = sqlite3.connect(DRYRUN_DB)
            cur = con.cursor()
            count = cur.execute("select count(*) from trades").fetchone()[0]
            row = cur.execute("select min(open_date), max(coalesce(close_date, open_date)) from trades").fetchone()
            spans.append({"source": str(DRYRUN_DB), "trade_count": count, "start": row[0], "end": row[1]})
        except Exception as exc:
            spans.append({"source": str(DRYRUN_DB), "error": repr(exc)})
    log_dates = []
    if DRYRUN_LOG.exists():
        for line in DRYRUN_LOG.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if m:
                try:
                    log_dates.append(dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
                except ValueError:
                    pass
    if log_dates:
        start = min(log_dates)
        end = max(log_dates)
        spans.append({"source": str(DRYRUN_LOG), "start": start.isoformat(sep=" "), "end": end.isoformat(sep=" "), "days": round((end - start).total_seconds() / 86400, 3)})
    max_days = max((float(s.get("days") or 0) for s in spans), default=0.0)
    return {
        "pass": max_days >= MIN_DRY_RUN_DAYS,
        "max_observed_days": max_days,
        "target_days": f"{MIN_DRY_RUN_DAYS}-{MAX_DRY_RUN_DAYS_TARGET}",
        "spans": spans,
        "message": "Dry-run duration requirement met." if max_days >= MIN_DRY_RUN_DAYS else "Dry-run has not run continuously for 2-4 weeks.",
    }


def dry_run_decision_log_gate() -> dict[str, Any]:
    decision_logs = list((PROJECT_ROOT / "reports").glob("**/*decision*.csv")) + list((PROJECT_ROOT / "reports").glob("**/*decision*.json"))
    trade_count = 0
    order_count = 0
    if DRYRUN_DB.exists():
        try:
            con = sqlite3.connect(DRYRUN_DB)
            cur = con.cursor()
            trade_count = int(cur.execute("select count(*) from trades").fetchone()[0])
            order_count = int(cur.execute("select count(*) from orders").fetchone()[0])
        except Exception:
            pass
    return {
        "pass": False,
        "decision_logs_found": [str(p) for p in decision_logs],
        "dry_run_trade_count": trade_count,
        "dry_run_order_count": order_count,
        "message": "No evidence that dry-run decision logs match actual dry-run fills/orders.",
    }


def lifecycle_gate() -> dict[str, Any]:
    scripts = {
        "start": PROJECT_ROOT / "scripts/start-native.sh",
        "stop": PROJECT_ROOT / "scripts/stop-native.sh",
        "status": PROJECT_ROOT / "scripts/status-native.sh",
        "report": PROJECT_ROOT / "scripts/pre-live-gate.sh",
    }
    exists = {name: path.exists() for name, path in scripts.items()}
    stability = STABILITY_LOG.exists() and "[PASS]" in STABILITY_LOG.read_text(encoding="utf-8", errors="ignore")
    return {
        "pass": all(exists.values()) and stability,
        "scripts": {name: str(path) for name, path in scripts.items()},
        "scripts_exist": exists,
        "stability_log": str(STABILITY_LOG) if STABILITY_LOG.exists() else "",
        "message": "Lifecycle scripts exist and a prior stability check exists." if all(exists.values()) and stability else "Missing lifecycle script or stability evidence.",
    }


def row(status: str, gate_id: int, name: str, message: str, evidence: Any) -> dict[str, Any]:
    return {"id": gate_id, "gate": name, "status": status, "message": message, "evidence": json.dumps(evidence, ensure_ascii=False, default=str)}


def write_csv(rows: list[dict[str, Any]]) -> None:
    with MATRIX_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "gate", "status", "message", "evidence"])
        writer.writeheader()
        writer.writerows(rows)


def write_report(rows: list[dict[str, Any]], approved: bool, details: dict[str, Any]) -> None:
    lines = [
        "# Pre-Live Trading Gate",
        "",
        f"Generated: `{now()}`",
        "",
        "**LIVE TRADING APPROVAL: " + ("PASS" if approved else "BLOCKED") + "**",
        "",
        "This gate is intentionally conservative. If any required item is not proven, real trading must remain disabled.",
        "",
        "## Gate Matrix",
        "| id | gate | status | message |",
        "|---:|---|---|---|",
    ]
    for item in rows:
        lines.append(f"| {item['id']} | {item['gate']} | `{item['status']}` | {item['message']} |")
    lines += [
        "",
        "## Current Decision",
    ]
    if approved:
        lines.append("- All gates passed. This script still does not enable live trading or add API keys.")
    else:
        lines.append("- Real trading is blocked. Keep `dry_run=True`; do not add real API keys.")
        lines.append("- Blocking items must be resolved with evidence before any live-trading discussion.")
    lines += [
        "",
        "## Important Evidence",
        f"- Backtest sample: `{details.get('sample_gate')}`",
        f"- Market states: `{details.get('market_state_gate')}`",
        f"- Fee/slippage: `{details.get('fee_slippage_gate')}`",
        f"- Dry-run span: `{details.get('dry_run_span')}`",
        f"- Safety: `{details.get('safety')}`",
        "",
        "## Outputs",
        "- `reports/pre_live_gate/pre_live_gate_report.md`",
        "- `reports/pre_live_gate/pre_live_gate_summary.json`",
        "- `reports/pre_live_gate/pre_live_gate_matrix.csv`",
        "- `reports/pre_live_gate/pre_live_gate_logs.txt`",
        "- `reports/pre_live_gate/LIVE_TRADING_BLOCKED.txt`",
    ]
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rec = Recorder()
    rec.section("Pre-live gate")
    rec.log(f"project: {PROJECT_ROOT}")
    rec.log(f"generated_at: {now()}")
    runtime_before = RUNTIME_CONFIG.read_bytes() if RUNTIME_CONFIG.exists() else b""
    sample = load_json(SAMPLE_SUMMARY, {})
    strategy = load_json(STRATEGY_SUMMARY, {})
    bt = read_backtest_export()

    checks = {
        "sample_gate": sample_gate(sample, bt),
        "market_state_gate": market_state_gate(strategy),
        "fee_slippage_gate": fee_slippage_gate(bt),
        "decision_engine_drawdown_gate": decision_engine_gate(),
        "decision_engine_false_kill_gate": decision_engine_gate(),
        "dry_run_span": dry_run_span(),
        "dry_run_decision_log_gate": dry_run_decision_log_gate(),
        "lifecycle_gate": lifecycle_gate(),
        "safety": safety_check(),
    }
    matrix = [
        row("PASS" if checks["sample_gate"]["pass"] else "FAIL", 1, "Backtest covers at least 365d and has 50-100 trades", checks["sample_gate"]["message"], checks["sample_gate"]),
        row("PASS" if checks["sample_gate"]["pass"] else "FAIL", 2, "Trade sample size is 50-100 trades", checks["sample_gate"]["message"], checks["sample_gate"]),
        row("PASS" if checks["market_state_gate"]["pass"] else "FAIL", 3, "Tested across up/down/range/panic/greed states", checks["market_state_gate"]["message"], checks["market_state_gate"]),
        row("PASS" if checks["fee_slippage_gate"]["pass"] else "FAIL", 4, "Fees and slippage assumptions included", checks["fee_slippage_gate"]["message"], checks["fee_slippage_gate"]),
        row("FAIL", 5, "Decision engine reduces maximum drawdown", checks["decision_engine_drawdown_gate"]["message"], checks["decision_engine_drawdown_gate"]),
        row("FAIL", 6, "Decision engine does not severely kill profitable signals", checks["decision_engine_false_kill_gate"]["message"], checks["decision_engine_false_kill_gate"]),
        row("PASS" if checks["dry_run_span"]["pass"] else "FAIL", 7, "Dry-run ran continuously for 2-4 weeks", checks["dry_run_span"]["message"], checks["dry_run_span"]),
        row("FAIL", 8, "Dry-run decision logs match actual fills/orders", checks["dry_run_decision_log_gate"]["message"], checks["dry_run_decision_log_gate"]),
        row("PASS" if checks["lifecycle_gate"]["pass"] else "FAIL", 9, "stop/start/status/report are stable", checks["lifecycle_gate"]["message"], checks["lifecycle_gate"]),
        row("PASS" if checks["safety"]["pass"] else "FAIL", 10, "Safety audit passed", "Runtime config remains dry-run spot-only with no credentials." if checks["safety"]["pass"] else "Safety audit failed.", checks["safety"]),
    ]
    runtime_after = RUNTIME_CONFIG.read_bytes() if RUNTIME_CONFIG.exists() else b""
    runtime_untouched = runtime_before == runtime_after
    if not runtime_untouched:
        matrix.append(row("FAIL", 99, "Runtime config unchanged by gate", "Runtime config changed during gate run.", {}))

    approved = all(item["status"] == "PASS" for item in matrix)
    write_csv(matrix)
    summary = {
        "generated_at": now(),
        "live_trading_approved": approved,
        "live_trading_blocked": not approved,
        "exit_code": 0 if approved else 2,
        "runtime_config_untouched": runtime_untouched,
        "checks": checks,
        "matrix": matrix,
        "required_action": "Keep dry_run=True. Do not add real API keys or enable live trading." if not approved else "All gates passed; manual human approval still required.",
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    write_report(matrix, approved, checks)
    if not approved:
        BLOCK_TXT.write_text(
            "LIVE TRADING BLOCKED\n"
            f"Generated: {now()}\n"
            "At least one pre-live gate failed. Keep dry_run=True. Do not add real API keys.\n",
            encoding="utf-8",
        )
    rec.section("Gate result")
    rec.log("LIVE_TRADING_APPROVED=" + str(approved))
    for item in matrix:
        rec.log(f"[{item['status']}] {item['id']}. {item['gate']} - {item['message']}")
    rec.section("Outputs")
    for path in (REPORT_MD, SUMMARY_JSON, MATRIX_CSV, LOG_TXT, BLOCK_TXT):
        rec.log(str(path))
    rec.write()
    return 0 if approved else 2


if __name__ == "__main__":
    sys.exit(main())
