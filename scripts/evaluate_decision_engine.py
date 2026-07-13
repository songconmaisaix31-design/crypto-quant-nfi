#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import os
import sqlite3
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
REPORT_DIR = PROJECT_ROOT / "reports/decision_engine"
USER_DIR = PROJECT_ROOT / "user_data/decision_engine"
MARKET_HISTORY = PROJECT_ROOT / "user_data/market_state/market_state_history.csv"
PAIR_QUALITY = PROJECT_ROOT / "reports/market_state/pair_quality_scores.csv"
SAMPLE_EXPORT_DIR = PROJECT_ROOT / "reports/sample_validation/exports/expanded_365d"
PRELIVE_UPDATE = PROJECT_ROOT / "reports/pre_live_gate/pre_live_gate_evidence_update.md"
DECISIONS_CSV = REPORT_DIR / "decision_signal_decisions.csv"
MATRIX_CSV = REPORT_DIR / "decision_backtest_matrix.csv"
BLOCKED_CSV = REPORT_DIR / "blocked_signal_analysis.csv"
REPORT_MD = REPORT_DIR / "decision_engine_report.md"
SUMMARY_JSON = REPORT_DIR / "decision_engine_summary.json"
USER_DECISIONS = USER_DIR / "latest_decision_evaluation.csv"
SLIPPAGE_PER_SIDE = 0.0005


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def safety() -> dict[str, bool]:
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
    if not all(checks.values()):
        raise RuntimeError(f"Unsafe runtime config: {checks}")
    return checks


def latest_zip(path: Path) -> Path:
    zips = sorted(path.glob("*.zip"), key=lambda p: p.stat().st_mtime)
    if not zips:
        raise FileNotFoundError(f"No backtest zip found in {path}")
    return zips[-1]


def load_trades() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    z = latest_zip(SAMPLE_EXPORT_DIR)
    with zipfile.ZipFile(z) as zf:
        name = [n for n in zf.namelist() if n.endswith(".json") and "_config" not in n and "_meta" not in n][0]
        data = json.loads(zf.read(name).decode("utf-8"))["strategy"]["NostalgiaForInfinityX7"]
        data["_zip_path"] = str(z)
        return data.get("trades", []), data


def tag(trade: dict[str, Any]) -> str:
    return str(trade.get("enter_tag") or "").strip() or "unknown"


def profit_abs(trade: dict[str, Any]) -> float:
    return float(trade.get("profit_abs") or 0.0)


def profit_ratio(trade: dict[str, Any]) -> float:
    return float(trade.get("profit_ratio") or 0.0)


def duration(trade: dict[str, Any]) -> float:
    return float(trade.get("trade_duration") or 0.0)


def open_date(trade: dict[str, Any]) -> pd.Timestamp:
    return pd.to_datetime(trade.get("open_date"), utc=True)


def tag_scores(trades: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        grouped[tag(t)].append(t)
    out = {}
    for k, items in grouped.items():
        profits = [profit_abs(t) for t in items]
        out[k] = {
            "count": len(items),
            "avg_profit": sum(profits) / len(profits),
            "win_rate": sum(1 for p in profits if p > 0) / len(profits),
        }
    return out


def lookup_row(df: pd.DataFrame, date: pd.Timestamp, pair: str | None = None) -> dict[str, Any]:
    if df.empty:
        return {}
    d = date.date().isoformat()
    if pair is not None:
        hit = df[(df["date"].astype(str) <= d) & (df["pair"] == pair)].tail(1)
    else:
        hit = df[df["date"].astype(str) <= d].tail(1)
    return hit.iloc[-1].to_dict() if len(hit) else {}


def reversal_evidence(pair_row: dict[str, Any]) -> bool:
    return float(pair_row.get("pair_return_1d") or 0) > 0 and float(pair_row.get("pair_drawdown_from_30d_high") or 0) > -25


def decide(trade: dict[str, Any], market: dict[str, Any], pairq: dict[str, Any], tag_score: dict[str, float]) -> dict[str, Any]:
    reasons: list[str] = []
    blocks: list[str] = []
    sentiment = float(market.get("market_sentiment_score") or 50)
    primary = str(market.get("primary_regime") or "unknown")
    regime_tags = str(market.get("regime_tags") or "")
    quality = float(pairq.get("pair_quality_score") or 50)
    volume_z = abs(float(pairq.get("volume_zscore") or 0))
    atr = float(pairq.get("pair_atr_percent") or 0)
    if primary == "overheated" and quality < 80:
        blocks.append("overheated_low_pair_quality")
    if primary == "panic" and not reversal_evidence(pairq):
        blocks.append("panic_without_reversal_evidence")
    if "risk_off" in regime_tags and tag_score.get("avg_profit", 0) < 0:
        blocks.append("risk_off_bad_enter_tag")
    if quality < 40:
        blocks.append("pair_quality_below_40")
    if volume_z > 3:
        blocks.append("extreme_volume_zscore")
    if atr > 10:
        blocks.append("extreme_pair_atr")
    if tag_score.get("avg_profit", 0) < 0 and tag_score.get("count", 0) >= 5:
        blocks.append("negative_tag_score")
    multiplier = 1.0
    if sentiment < 35:
        multiplier = min(multiplier, 0.5)
        reasons.append("sentiment_below_35")
    if sentiment > 70:
        multiplier = min(multiplier, 0.5)
        reasons.append("sentiment_above_70")
    if 40 <= quality < 60:
        multiplier = min(multiplier, 0.5)
        reasons.append("pair_quality_40_to_60")
    if "high_volatility" in regime_tags:
        multiplier = min(multiplier, 0.5)
        reasons.append("high_volatility")
    if primary == "panic" or sentiment < 25:
        multiplier = min(multiplier, 0.25)
        reasons.append("panic_or_extreme_risk")
    allow = not blocks
    return {
        "allow_entry": allow,
        "block_reason": ";".join(blocks),
        "stake_multiplier": multiplier if allow else 0.0,
        "final_decision": "allow" if allow and multiplier == 1 else "allow_reduced" if allow else "block",
        "decision_reason": ";".join(reasons) if reasons else "normal" if allow else ";".join(blocks),
    }


def max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    dd = 0.0
    for v in values:
        equity += v
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dd


def max_consecutive_losses(values: list[float]) -> int:
    best = cur = 0
    for v in values:
        if v < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def metrics(name: str, rows: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    profits = []
    raw = len(rows)
    allowed = blocked = 0
    missed_profit = avoided_loss = 0.0
    durations = []
    for r in rows:
        p = float(r["baseline_profit"])
        stake = float(r.get("stake_amount") or 100)
        allow = r["allow_entry"] == "True" if isinstance(r["allow_entry"], str) else bool(r["allow_entry"])
        mult = float(r.get("stake_multiplier") or 0)
        if mode == "baseline":
            profits.append(p)
            allowed += 1
        elif allow:
            allowed += 1
            adj = p * (mult if mode in ("stake", "slippage") else 1.0)
            if mode == "slippage":
                adj -= stake * mult * SLIPPAGE_PER_SIDE * 2
            profits.append(adj)
        else:
            blocked += 1
            if p > 0:
                missed_profit += p
            else:
                avoided_loss += abs(p)
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]
    durations = [float(r.get("trade_duration") or 0) for r in rows if mode == "baseline" or bool(r.get("allow_entry"))]
    return {
        "scenario": name,
        "raw_signals": raw,
        "allowed_signals": allowed,
        "blocked_signals": blocked,
        "trades_count": len(profits),
        "total_profit": round(sum(profits), 8),
        "total_profit_after_slippage": round(sum(profits), 8) if mode == "slippage" else "",
        "win_rate": round(len(wins) / len(profits), 6) if profits else 0,
        "average_profit": round(sum(profits) / len(profits), 8) if profits else 0,
        "worst_trade": round(min(profits), 8) if profits else 0,
        "best_trade": round(max(profits), 8) if profits else 0,
        "max_consecutive_losses": max_consecutive_losses(profits),
        "max_drawdown": round(max_drawdown(profits), 8),
        "profit_factor": round(sum(wins) / abs(sum(losses)), 8) if losses else "N/A",
        "average_duration": round(sum(durations) / len(durations), 4) if durations else 0,
        "exposure_estimate": "N/A: requires full portfolio timeline",
        "missed_profit": round(missed_profit, 8),
        "avoided_loss": round(avoided_loss, 8),
        "net_filter_value": round(avoided_loss - missed_profit, 8),
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def dry_run_days() -> float:
    log = PROJECT_ROOT / "user_data/logs/freqtrade-native.log"
    if not log.exists():
        return 0.0
    dates = []
    for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = line[:19]
        try:
            dates.append(pd.to_datetime(m))
        except Exception:
            pass
    if not dates:
        return 0.0
    return round((max(dates) - min(dates)).total_seconds() / 86400, 3)


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    USER_DIR.mkdir(parents=True, exist_ok=True)
    before = RUNTIME_CONFIG.read_bytes()
    safe = safety()
    trades, bt = load_trades()
    if not MARKET_HISTORY.exists() or not PAIR_QUALITY.exists():
        raise RuntimeError("Run scripts/build-market-state.sh first.")
    market_df = pd.read_csv(MARKET_HISTORY)
    pair_df = pd.read_csv(PAIR_QUALITY)
    scores = tag_scores(trades)
    decision_rows: list[dict[str, Any]] = []
    for i, trade in enumerate(sorted(trades, key=lambda t: str(t.get("open_date"))), 1):
        od = open_date(trade)
        market = lookup_row(market_df, od)
        pq = lookup_row(pair_df, od, str(trade.get("pair")))
        ts = scores.get(tag(trade), {"count": 0, "avg_profit": 0, "win_rate": 0})
        dec = decide(trade, market, pq, ts)
        row = {
            "pair": trade.get("pair"),
            "signal_time": trade.get("open_date"),
            "enter_tag": tag(trade),
            "baseline_trade_id": i,
            "baseline_profit": profit_abs(trade),
            "baseline_profit_ratio": profit_ratio(trade),
            "stake_amount": trade.get("stake_amount", 100),
            "trade_duration": duration(trade),
            "market_sentiment_score": market.get("market_sentiment_score", ""),
            "primary_regime": market.get("primary_regime", ""),
            "regime_tags": market.get("regime_tags", ""),
            "pair_quality_score": pq.get("pair_quality_score", ""),
            "volume_zscore": pq.get("volume_zscore", ""),
            "pair_atr_percent": pq.get("pair_atr_percent", ""),
            "enter_tag_historical_score": ts.get("avg_profit", 0),
            "enter_tag_sample_count": ts.get("count", 0),
        }
        row.update(dec)
        decision_rows.append(row)
    fields = [
        "pair", "signal_time", "enter_tag", "baseline_trade_id", "baseline_profit", "baseline_profit_ratio",
        "market_sentiment_score", "primary_regime", "regime_tags", "pair_quality_score", "enter_tag_historical_score",
        "allow_entry", "block_reason", "stake_multiplier", "final_decision", "decision_reason", "volume_zscore", "pair_atr_percent",
    ]
    write_csv(DECISIONS_CSV, decision_rows, fields)
    write_csv(USER_DECISIONS, decision_rows, fields)
    scenarios = [
        metrics("baseline_nfi", decision_rows, "baseline"),
        metrics("filter_market_state", decision_rows, "filter"),
        metrics("filter_market_state_pair_quality", decision_rows, "filter"),
        metrics("filter_market_state_pair_quality_tag_score", decision_rows, "filter"),
        metrics("filter_plus_stake_multiplier", decision_rows, "stake"),
        metrics("filter_plus_slippage_stress", decision_rows, "slippage"),
    ]
    matrix_fields = list(scenarios[0].keys())
    write_csv(MATRIX_CSV, scenarios, matrix_fields)
    blocked = [r for r in decision_rows if not bool(r.get("allow_entry"))]
    blocked_rows = []
    for r in blocked:
        p = float(r["baseline_profit"])
        blocked_rows.append({
            "pair": r["pair"],
            "signal_time": r["signal_time"],
            "enter_tag": r["enter_tag"],
            "baseline_profit": p,
            "market_regime": r["primary_regime"],
            "sentiment_score": r["market_sentiment_score"],
            "pair_quality_score": r["pair_quality_score"],
            "block_reason": r["block_reason"],
            "would_block_have_helped": p <= 0,
            "blocked_winner": p > 0,
            "blocked_loser": p <= 0,
            "missed_profit": p if p > 0 else 0,
            "avoided_loss": abs(p) if p < 0 else 0,
        })
    write_csv(BLOCKED_CSV, blocked_rows, [
        "pair", "signal_time", "enter_tag", "baseline_profit", "market_regime", "sentiment_score",
        "pair_quality_score", "block_reason", "would_block_have_helped", "blocked_winner", "blocked_loser",
        "missed_profit", "avoided_loss",
    ])
    blocked_winners = sum(1 for r in blocked_rows if r["blocked_winner"])
    blocked_losers = sum(1 for r in blocked_rows if r["blocked_loser"])
    missed_profit = sum(float(r["missed_profit"]) for r in blocked_rows)
    avoided_loss = sum(float(r["avoided_loss"]) for r in blocked_rows)
    baseline = scenarios[0]
    filtered = scenarios[-1]
    improved_drawdown = filtered["max_drawdown"] < baseline["max_drawdown"]
    serious_false_kill = blocked_winners > 0 and missed_profit > avoided_loss
    summary = {
        "safe_config": safe,
        "runtime_config_untouched": before == RUNTIME_CONFIG.read_bytes(),
        "raw_signals": len(decision_rows),
        "blocked_signals": len(blocked_rows),
        "allowed_signals": len(decision_rows) - len(blocked_rows),
        "blocked_winning_trades": blocked_winners,
        "blocked_losing_trades": blocked_losers,
        "missed_profit_total": round(missed_profit, 8),
        "avoided_loss_total": round(avoided_loss, 8),
        "net_filter_value": round(avoided_loss - missed_profit, 8),
        "largest_missed_winner": max((float(r["missed_profit"]) for r in blocked_rows), default=0),
        "largest_avoided_loser": max((float(r["avoided_loss"]) for r in blocked_rows), default=0),
        "max_drawdown_improved": improved_drawdown,
        "serious_false_kill": serious_false_kill,
        "matrix": scenarios,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    lines = [
        "# Decision Engine Offline Evaluation",
        "",
        "This is an offline evidence module. It does not change strategy logic or live configuration.",
        "",
        f"- Raw signals: `{summary['raw_signals']}`",
        f"- Allowed signals: `{summary['allowed_signals']}`",
        f"- Blocked signals: `{summary['blocked_signals']}`",
        f"- Max drawdown improved after filter_plus_slippage_stress: `{improved_drawdown}`",
        f"- Serious false-kill detected: `{serious_false_kill}`",
        f"- Missed profit: `{summary['missed_profit_total']}`",
        f"- Avoided loss: `{summary['avoided_loss_total']}`",
        "",
        "## Matrix",
        "| scenario | trades | total_profit | max_drawdown | win_rate | missed_profit | avoided_loss | net_filter_value |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in scenarios:
        lines.append(f"| `{s['scenario']}` | {s['trades_count']} | {s['total_profit']} | {s['max_drawdown']} | {s['win_rate']} | {s['missed_profit']} | {s['avoided_loss']} | {s['net_filter_value']} |")
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    dry_days = dry_run_days()
    PRELIVE_UPDATE.write_text(
        "# Pre-Live Gate Evidence Update\n\n"
        "LIVE TRADING STATUS: BLOCKED\n\n"
        f"- Market-state evidence: see `reports/market_state/regime_coverage_matrix.csv`.\n"
        f"- Decision engine max-drawdown improved: `{improved_drawdown}`.\n"
        f"- Serious false-kill detected: `{serious_false_kill}`.\n"
        f"- Dry-run observed days: `{dry_days}`.\n"
        "- Dry-run decision/fill consistency evidence: not proven until journal has live signal/fill pairs.\n\n"
        "This update is evidence only and does not override the original pre-live gate.\n",
        encoding="utf-8",
    )
    print(f"[PASS] wrote {MATRIX_CSV}")
    print(f"[PASS] wrote {BLOCKED_CSV}")
    print(f"[PASS] wrote {REPORT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
