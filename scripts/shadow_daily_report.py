#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
REPORT_OUT = PROJECT_ROOT / "reports/decision_engine_shadow"
USER_OUT = PROJECT_ROOT / "user_data/decision_engine_shadow"
JOURNAL = REPORT_OUT / "shadow_decision_journal.csv"
OUTCOMES = REPORT_OUT / "shadow_trade_outcomes.csv"
CONSISTENCY = REPORT_OUT / "shadow_consistency_matrix.csv"
DAILY_MD = REPORT_OUT / "shadow_daily_report.md"
DAILY_JSON = REPORT_OUT / "shadow_daily_summary.json"
METRICS_HISTORY = REPORT_OUT / "shadow_metrics_history.csv"
PRELIVE_UPDATE = PROJECT_ROOT / "reports/pre_live_gate/pre_live_gate_shadow_evidence_update.md"
MARKET_LATEST = PROJECT_ROOT / "user_data/market_state/market_state_latest.json"
FROZEN_META = USER_OUT / "frozen_v2_metadata.json"
SLIPPAGE_PER_SIDE = 0.0005


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_csv(path: Path, row: dict[str, Any], fields: list[str]) -> None:
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in fields})


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except Exception:
        return default


def safety_check() -> dict[str, Any]:
    cfg = load_json(RUNTIME_CONFIG, {})
    ex = cfg.get("exchange", {})
    api = cfg.get("api_server", {})
    checks = {
        "dry_run": cfg.get("dry_run") is True,
        "trading_mode_spot": cfg.get("trading_mode") == "spot",
        "margin_mode_empty": cfg.get("margin_mode") in ("", None),
        "can_short_false": cfg.get("can_short") is False,
        "credentials_empty": not (ex.get("key") or ex.get("secret") or ex.get("password")),
        "api_localhost": api.get("listen_ip_address") == "127.0.0.1",
    }
    return {"checks": checks, "pass": all(checks.values())}


def parse_time(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def max_drawdown(values: list[float]) -> float:
    equity = peak = dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dd


def max_consecutive_losses(values: list[float]) -> int:
    best = cur = 0
    for value in values:
        if value < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def summarize() -> dict[str, Any]:
    journal = read_csv(JOURNAL)
    outcomes = read_csv(OUTCOMES)
    safety = safety_check()
    latest = load_json(MARKET_LATEST, {})
    frozen = load_json(FROZEN_META, {})
    dates = sorted({(r.get("journal_time") or "")[:10] for r in journal if r.get("journal_time")})
    observation_days = len(dates)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    today_rows = [r for r in journal if (r.get("journal_time") or "").startswith(today)]
    trade_rows = [r for r in journal if r.get("observation_status") == "observed_dry_run_trade"]
    closed = [r for r in outcomes if r.get("v2_outcome_label") not in ("", "pending")]
    allowed_closed = [r for r in closed if str(r.get("would_v2_have_allowed")).lower() in ("true", "1", "yes")]
    blocked_closed = [r for r in closed if str(r.get("would_v2_have_blocked")).lower() in ("true", "1", "yes")]
    labels: dict[str, int] = {}
    for row in outcomes:
        labels[row.get("v2_outcome_label") or "unknown"] = labels.get(row.get("v2_outcome_label") or "unknown", 0) + 1
    wrong_block_winner = labels.get("wrong_block_winner", 0)
    correct_block_loser = labels.get("correct_block_loser", 0)
    missed_profit = sum(as_float(r.get("profit_ratio")) for r in blocked_closed if as_float(r.get("profit_ratio")) > 0)
    avoided_loss = abs(sum(as_float(r.get("profit_ratio")) for r in blocked_closed if as_float(r.get("profit_ratio")) <= 0))
    net_forward_filter_value = avoided_loss - missed_profit
    allowed_profit_after_slippage = sum(as_float(r.get("profit_ratio")) - (SLIPPAGE_PER_SIDE * 2) for r in allowed_closed)
    baseline_profits = [as_float(r.get("profit_ratio")) for r in closed]
    v2_allowed_profits = [as_float(r.get("profit_ratio")) - (SLIPPAGE_PER_SIDE * 2) for r in allowed_closed]
    consistency_candidates = [r for r in journal if r.get("consistency_status") in ("v2_allow_and_dry_run_opened", "v2_block_but_dry_run_opened", "v2_allow_but_no_dry_run_trade")]
    consistent = [r for r in consistency_candidates if r.get("consistency_status") == "v2_allow_and_dry_run_opened"]
    consistency_rate = (len(consistent) / len(consistency_candidates)) if consistency_candidates else None
    summary = {
        "generated_at": now(),
        "rule_version": frozen.get("rule_version", ""),
        "config_hash": frozen.get("config_hash", ""),
        "safe_config": safety["pass"],
        "safety_checks": safety["checks"],
        "bot_running": any(str(r.get("bot_running")).lower() == "true" for r in journal[-5:]) if journal else False,
        "dry_run": safety["checks"].get("dry_run"),
        "today_market_regime": latest.get("primary_regime", ""),
        "today_regime_tags": latest.get("regime_tags", ""),
        "today_fear_greed": latest.get("fear_greed_value", latest.get("fear_and_greed", "")),
        "today_open_trades": sum(1 for r in outcomes if r.get("v2_outcome_label") == "pending"),
        "today_closed_trades": len([r for r in closed if (r.get("close_date") or "").startswith(today)]),
        "today_new_observed_signals": len(today_rows),
        "v2_allow_count": sum(1 for r in journal if (r.get("v2_decision") or "").startswith("allow")),
        "v2_block_count": sum(1 for r in journal if r.get("v2_decision") == "block"),
        "actual_dry_run_open_count": len(trade_rows),
        "consistency_rate": None if consistency_rate is None else round(consistency_rate, 6),
        "consistency_status_counts": {r.get("consistency_status") or "unknown": sum(1 for x in journal if (x.get("consistency_status") or "unknown") == (r.get("consistency_status") or "unknown")) for r in journal},
        "pending_trades": labels.get("pending", 0),
        "closed_trades": len(closed),
        "forward_closed_trades": len(closed),
        "correct_allow_winner": labels.get("correct_allow_winner", 0),
        "wrong_allow_loser": labels.get("wrong_allow_loser", 0),
        "correct_block_loser": correct_block_loser,
        "wrong_block_winner": wrong_block_winner,
        "net_forward_filter_value": round(net_forward_filter_value, 8),
        "allowed_profit_after_slippage": round(allowed_profit_after_slippage, 8),
        "observation_days": observation_days,
        "days_to_14": max(0, 14 - observation_days),
        "days_to_28": max(0, 28 - observation_days),
        "baseline_max_drawdown": round(max_drawdown(baseline_profits), 8),
        "v2_allowed_max_drawdown": round(max_drawdown(v2_allowed_profits), 8),
        "baseline_max_consecutive_losses": max_consecutive_losses(baseline_profits),
        "v2_allowed_max_consecutive_losses": max_consecutive_losses(v2_allowed_profits),
        "pre_live_gate_status": "BLOCKED",
        "notes": "Shadow mode is observation-only and does not control orders.",
    }
    return summary


def write_report(summary: dict[str, Any]) -> None:
    lines = [
        "# Decision Engine Shadow Daily Report",
        "",
        f"Generated: `{summary['generated_at']}`",
        "",
        "Shadow mode is read-only. It records what v2 would have done and compares that with dry-run observations.",
        "",
        "## Status",
        f"- Bot running evidence: `{summary['bot_running']}`",
        f"- Dry-run: `{summary['dry_run']}`",
        f"- Safety passed: `{summary['safe_config']}`",
        f"- Rule version: `{summary['rule_version']}`",
        f"- Config hash: `{summary['config_hash']}`",
        "",
        "## Today",
        f"- Market regime: `{summary['today_market_regime']}` `{summary['today_regime_tags']}`",
        f"- Fear & Greed: `{summary['today_fear_greed']}`",
        f"- Open trades: `{summary['today_open_trades']}`",
        f"- Closed trades today: `{summary['today_closed_trades']}`",
        f"- New observed signals/heartbeats today: `{summary['today_new_observed_signals']}`",
        "",
        "## Forward Evidence",
        f"- Forward closed trades: `{summary['forward_closed_trades']}`",
        f"- V2 allow/block counts: `{summary['v2_allow_count']}` / `{summary['v2_block_count']}`",
        f"- Actual dry-run observed trades: `{summary['actual_dry_run_open_count']}`",
        f"- Consistency rate: `{summary['consistency_rate']}`",
        f"- Correct allow winner: `{summary['correct_allow_winner']}`",
        f"- Wrong allow loser: `{summary['wrong_allow_loser']}`",
        f"- Correct block loser: `{summary['correct_block_loser']}`",
        f"- Wrong block winner: `{summary['wrong_block_winner']}`",
        f"- Net forward filter value: `{summary['net_forward_filter_value']}`",
        f"- V2 allowed profit after slippage: `{summary['allowed_profit_after_slippage']}`",
        f"- Observation days: `{summary['observation_days']}`",
        f"- Days to 14 / 28: `{summary['days_to_14']}` / `{summary['days_to_28']}`",
        "",
        "## Gate Reminder",
        "- Pre-live gate remains `BLOCKED` unless every hard gate is satisfied and manual review passes.",
    ]
    DAILY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_prelive_update(summary: dict[str, Any]) -> None:
    lines = [
        "# Pre-Live Gate Shadow Evidence Update",
        "",
        "LIVE TRADING STATUS: BLOCKED",
        "",
        f"- Shadow mode recording: `{JOURNAL.exists()}`.",
        f"- Observation days: `{summary['observation_days']}`.",
        f"- Forward closed trades: `{summary['forward_closed_trades']}`.",
        f"- Net forward filter value: `{summary['net_forward_filter_value']}`.",
        f"- Wrong block winner / correct block loser: `{summary['wrong_block_winner']}` / `{summary['correct_block_loser']}`.",
        f"- V2 allowed profit after slippage: `{summary['allowed_profit_after_slippage']}`.",
        f"- Dry-run consistency rate: `{summary['consistency_rate']}`.",
        f"- 14-day requirement met: `{summary['observation_days'] >= 14}`.",
        f"- 28-day preferred target met: `{summary['observation_days'] >= 28}`.",
        "",
        "This evidence is forward dry-run observation only. It does not approve live trading.",
    ]
    PRELIVE_UPDATE.parent.mkdir(parents=True, exist_ok=True)
    PRELIVE_UPDATE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    REPORT_OUT.mkdir(parents=True, exist_ok=True)
    summary = summarize()
    DAILY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    write_report(summary)
    write_prelive_update(summary)
    fields = [
        "generated_at",
        "observation_days",
        "forward_closed_trades",
        "consistency_rate",
        "wrong_block_winner",
        "correct_block_loser",
        "net_forward_filter_value",
        "allowed_profit_after_slippage",
        "baseline_max_drawdown",
        "v2_allowed_max_drawdown",
        "baseline_max_consecutive_losses",
        "v2_allowed_max_consecutive_losses",
        "pre_live_gate_status",
    ]
    append_csv(METRICS_HISTORY, summary, fields)
    print(f"[PASS] wrote {DAILY_MD}")
    print(f"[PASS] wrote {DAILY_JSON}")
    print("[BLOCKED] pre-live gate remains BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
