#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
REPORT_DIR = PROJECT_ROOT / "reports/pre_live_gate"
SHADOW_SUMMARY = PROJECT_ROOT / "reports/decision_engine_shadow/shadow_daily_summary.json"
MANUAL_REVIEW = PROJECT_ROOT / "reports/pre_live_gate/manual_review_v3.json"
REPORT_MD = REPORT_DIR / "pre_live_gate_v3_report.md"
SUMMARY_JSON = REPORT_DIR / "pre_live_gate_v3_summary.json"
MATRIX_CSV = REPORT_DIR / "pre_live_gate_v3_matrix.csv"
LOG_TXT = REPORT_DIR / "pre_live_gate_v3_logs.txt"
BLOCK_TXT = REPORT_DIR / "LIVE_TRADING_BLOCKED_V3.txt"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


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
    return {"pass": all(checks.values()), "checks": checks}


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except Exception:
        return default


def row(gate_id: int, gate: str, passed: bool, message: str, evidence: Any) -> dict[str, Any]:
    return {
        "id": gate_id,
        "gate": gate,
        "status": "PASS" if passed else "FAIL",
        "message": message,
        "evidence": json.dumps(evidence, ensure_ascii=False, default=str),
    }


def manual_review_gate() -> dict[str, Any]:
    review = load_json(MANUAL_REVIEW, {})
    approved = review.get("approved") is True and bool(review.get("reviewer")) and bool(review.get("reviewed_at"))
    return {
        "pass": approved,
        "review_file": str(MANUAL_REVIEW),
        "review_present": MANUAL_REVIEW.exists(),
        "reviewer": review.get("reviewer", ""),
        "reviewed_at": review.get("reviewed_at", ""),
        "message": "Manual review approved." if approved else "Manual review approval file is missing or not approved.",
    }


def build_matrix(shadow: dict[str, Any], safety: dict[str, Any], manual: dict[str, Any]) -> list[dict[str, Any]]:
    obs_days = int(shadow.get("observation_days") or 0)
    forward_closed = int(shadow.get("forward_closed_trades") or 0)
    net_value = as_float(shadow.get("net_forward_filter_value"))
    wrong_block = int(shadow.get("wrong_block_winner") or 0)
    correct_block = int(shadow.get("correct_block_loser") or 0)
    allowed_after_slippage = as_float(shadow.get("allowed_profit_after_slippage"))
    consistency = shadow.get("consistency_rate")
    consistency_val = None if consistency is None else as_float(consistency)
    base_losses = int(shadow.get("baseline_max_consecutive_losses") or 0)
    v2_losses = int(shadow.get("v2_allowed_max_consecutive_losses") or 0)
    base_dd = as_float(shadow.get("baseline_max_drawdown"))
    v2_dd = as_float(shadow.get("v2_allowed_max_drawdown"))
    wrong_block_ok = wrong_block <= correct_block if correct_block > 0 else wrong_block == 0
    rows = [
        row(1, "Shadow observation >= 14 days, preferred 28 days", obs_days >= 14, f"Observed {obs_days} day(s); 14 required, 28 preferred.", {"observation_days": obs_days, "preferred_days": 28}),
        row(2, "Forward closed trades >= 20", forward_closed >= 20, f"Forward closed trades: {forward_closed}; at least 20 required.", {"forward_closed_trades": forward_closed}),
        row(3, "net_forward_filter_value > 0", net_value > 0, f"net_forward_filter_value={net_value}.", {"net_forward_filter_value": net_value}),
        row(4, "wrong_block_winner not greater than correct_block_loser", wrong_block_ok, f"wrong_block_winner={wrong_block}, correct_block_loser={correct_block}.", {"wrong_block_winner": wrong_block, "correct_block_loser": correct_block}),
        row(5, "V2 allowed trades remain positive after slippage", allowed_after_slippage > 0, f"allowed_profit_after_slippage={allowed_after_slippage}.", {"allowed_profit_after_slippage": allowed_after_slippage}),
        row(6, "Dry-run decision consistency >= 95%", consistency_val is not None and consistency_val >= 0.95, f"consistency_rate={consistency}.", {"consistency_rate": consistency}),
        row(7, "Consecutive losses did not worsen", v2_losses <= base_losses and forward_closed > 0, f"baseline={base_losses}, v2_allowed={v2_losses}.", {"baseline_max_consecutive_losses": base_losses, "v2_allowed_max_consecutive_losses": v2_losses}),
        row(8, "Maximum drawdown below baseline dry-run", v2_dd < base_dd and forward_closed > 0, f"baseline_drawdown={base_dd}, v2_allowed_drawdown={v2_dd}.", {"baseline_max_drawdown": base_dd, "v2_allowed_max_drawdown": v2_dd}),
        row(9, "Safety audit: no API key, futures, margin, leverage, short", safety["pass"], "Runtime safety passed." if safety["pass"] else "Runtime safety failed.", safety),
        row(10, "Manual review passed", manual["pass"], manual["message"], manual),
    ]
    return rows


def write_csv(rows: list[dict[str, Any]]) -> None:
    with MATRIX_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "gate", "status", "message", "evidence"])
        writer.writeheader()
        writer.writerows(rows)


def write_report(rows: list[dict[str, Any]], approved: bool, shadow: dict[str, Any]) -> None:
    lines = [
        "# Pre-Live Gate V3",
        "",
        f"Generated: `{now()}`",
        "",
        "**LIVE TRADING APPROVAL: " + ("PASS" if approved else "BLOCKED") + "**",
        "",
        "V3 requires forward dry-run shadow evidence. Offline backtests and v2 calibration alone are not enough.",
        "",
        "## Gate Matrix",
        "| id | gate | status | message |",
        "|---:|---|---|---|",
    ]
    for item in rows:
        lines.append(f"| {item['id']} | {item['gate']} | `{item['status']}` | {item['message']} |")
    lines += [
        "",
        "## Shadow Snapshot",
        f"- Rule version: `{shadow.get('rule_version', '')}`",
        f"- Config hash: `{shadow.get('config_hash', '')}`",
        f"- Observation days: `{shadow.get('observation_days', 0)}`",
        f"- Forward closed trades: `{shadow.get('forward_closed_trades', 0)}`",
        f"- Net forward filter value: `{shadow.get('net_forward_filter_value', 0)}`",
        f"- Consistency rate: `{shadow.get('consistency_rate')}`",
        "",
        "## Decision",
    ]
    if approved:
        lines.append("- All V3 gates passed. This script still does not enable live trading or add API keys.")
    else:
        lines.append("- Real trading remains blocked. Keep `dry_run=True`; do not add real API keys.")
        lines.append("- A human approval file alone is not enough; every evidence gate must pass too.")
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    before = RUNTIME_CONFIG.read_bytes() if RUNTIME_CONFIG.exists() else b""
    shadow = load_json(SHADOW_SUMMARY, {})
    safety = safety_check()
    manual = manual_review_gate()
    rows = build_matrix(shadow, safety, manual)
    runtime_untouched = before == (RUNTIME_CONFIG.read_bytes() if RUNTIME_CONFIG.exists() else b"")
    if not runtime_untouched:
        rows.append(row(99, "Runtime config unchanged by V3 gate", False, "Runtime config changed during V3 gate run.", {}))
    approved = all(item["status"] == "PASS" for item in rows)
    write_csv(rows)
    summary = {
        "generated_at": now(),
        "version": 3,
        "live_trading_approved": approved,
        "live_trading_blocked": not approved,
        "exit_code": 0 if approved else 2,
        "runtime_config_untouched": runtime_untouched,
        "shadow_summary_file": str(SHADOW_SUMMARY),
        "manual_review_file": str(MANUAL_REVIEW),
        "shadow": shadow,
        "safety": safety,
        "matrix": rows,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    write_report(rows, approved, shadow)
    if not approved:
        BLOCK_TXT.write_text(
            "LIVE TRADING BLOCKED BY PRE-LIVE GATE V3\n"
            f"Generated: {now()}\n"
            "Shadow observation, forward-trade evidence, safety, and manual review must all pass before live trading.\n",
            encoding="utf-8",
        )
    LOG_TXT.write_text("\n".join([f"generated_at={now()}", f"approved={approved}", f"runtime_config_untouched={runtime_untouched}"]) + "\n", encoding="utf-8")
    print("LIVE_TRADING_APPROVED=" + str(approved))
    for item in rows:
        print(f"[{item['status']}] {item['id']}. {item['gate']} - {item['message']}")
    print(f"[PASS] wrote {REPORT_MD}")
    print(f"[PASS] wrote {SUMMARY_JSON}")
    if not approved:
        print("[BLOCKED] pre-live gate v3 remains BLOCKED")
    return 0 if approved else 2


if __name__ == "__main__":
    sys.exit(main())
