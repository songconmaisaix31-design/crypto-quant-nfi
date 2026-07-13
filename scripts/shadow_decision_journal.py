#!/usr/bin/env python3
from __future__ import annotations

import base64
import csv
import datetime as dt
import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
CANDIDATES_CONFIG = PROJECT_ROOT / "configs/shadow_decision_candidates.yaml"
MARKET_LATEST = PROJECT_ROOT / "user_data/market_state/market_state_latest.json"
MARKET_HISTORY = PROJECT_ROOT / "user_data/market_state/market_state_history.csv"
PAIR_QUALITY = PROJECT_ROOT / "reports/market_state/pair_quality_scores.csv"
V2_SUMMARY = PROJECT_ROOT / "reports/decision_engine_v2/decision_engine_v2_summary.json"
V2_JOURNAL = PROJECT_ROOT / "user_data/decision_engine_v2/latest_v2_decision_journal.csv"
DRYRUN_JOURNAL = PROJECT_ROOT / "reports/dry_run_journal/dry_run_decision_journal.csv"
DRYRUN_DB = PROJECT_ROOT / "user_data/tradesv3.dryrun.sqlite"
LOG_DIR = PROJECT_ROOT / "user_data/logs"
REPORT_OUT = PROJECT_ROOT / "reports/shadow_decision"
USER_OUT = PROJECT_ROOT / "user_data/shadow_decision"
JOURNAL = REPORT_OUT / "shadow_decision_journal.csv"
SUMMARY = REPORT_OUT / "shadow_decision_summary.json"
COMPARISON = REPORT_OUT / "shadow_candidate_comparison.csv"
CONSISTENCY = REPORT_OUT / "shadow_consistency_check.csv"
BLOCKED = REPORT_OUT / "shadow_blocked_missed_analysis.csv"
LOGS = REPORT_OUT / "shadow_decision_logs.txt"
SNAPSHOT = USER_OUT / "latest_shadow_snapshot.json"
SIGNAL_SNAPSHOT = USER_OUT / "latest_signal_snapshot.json"
PRELIVE_UPDATE = PROJECT_ROOT / "reports/pre_live_gate/pre_live_gate_shadow_evidence_update.md"
SLIPPAGE_PER_SIDE = 0.0005

CANDIDATES = ["baseline_nfi", "decision_engine_v2_frozen", "decision_engine_v2_relaxed", "sizing_only"]

JOURNAL_FIELDS = [
    "snapshot_time",
    "event_type",
    "pair",
    "signal_time",
    "trade_open_time",
    "enter_tag",
    "market_sentiment_score",
    "primary_regime",
    "regime_tags",
    "pair_quality_score",
    "volume_zscore",
    "pair_atr_percent",
    "candidate_name",
    "candidate_decision",
    "stake_multiplier",
    "decision_reason",
    "dry_run_trade_created",
    "dry_run_trade_id",
    "dry_run_open_rate",
    "dry_run_current_profit",
    "dry_run_close_profit",
    "consistency_status",
    "signal_detection_status",
    "signal_check_method",
    "confirmed_signal_count",
    "confirmed_no_signal_count",
    "inferred_signal_count",
    "signal_check_notes",
    "notes",
]


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


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def append_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    if path.exists() and path.stat().st_size > 0:
        with path.open(newline="", encoding="utf-8") as f:
            existing_fields = (csv.DictReader(f).fieldnames or [])
        if existing_fields != fields:
            existing_rows = read_csv(path)
            write_csv(path, existing_rows, fields)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except Exception:
        return default


def parse_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


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
    return {"pass": all(checks.values()), "checks": checks, "config": cfg}


def api_request(cfg: dict[str, Any], endpoint: str, timeout: float = 2.0) -> tuple[bool, Any, str]:
    api = cfg.get("api_server", {})
    host = api.get("listen_ip_address") or "127.0.0.1"
    port = api.get("listen_port") or 8080
    req = urllib.request.Request(f"http://{host}:{port}{endpoint}")
    username = api.get("username")
    password = api.get("password")
    if username and password:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
            try:
                return True, json.loads(text), ""
            except json.JSONDecodeError:
                return True, text, ""
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}"


def read_freqtrade_status(cfg: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"api_available": False, "errors": {}, "data": {}}
    for name, endpoint in {
        "ping": "/api/v1/ping",
        "status": "/api/v1/status",
        "count": "/api/v1/count",
        "profit": "/api/v1/profit",
        "balance": "/api/v1/balance",
    }.items():
        ok, data, err = api_request(cfg, endpoint)
        if ok:
            result["api_available"] = True
            result["data"][name] = data
        else:
            result["errors"][name] = err
    return result


def read_db_trades() -> list[dict[str, Any]]:
    if not DRYRUN_DB.exists():
        return []
    con = sqlite3.connect(DRYRUN_DB)
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute("select * from trades order by open_date asc, id asc").fetchall()]


def read_db_orders() -> list[dict[str, Any]]:
    if not DRYRUN_DB.exists():
        return []
    try:
        con = sqlite3.connect(DRYRUN_DB)
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("select * from orders order by order_date desc limit 20").fetchall()]
    except Exception:
        return []


def bot_running_from_logs() -> tuple[bool, str, list[str]]:
    errors: list[str] = []
    heartbeat = ""
    for path in sorted(LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:6]:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in lines[-500:]:
            low = line.lower()
            if "heartbeat" in low or "state changed to: running" in low or "freqtradebot is running" in low:
                heartbeat = line[-240:]
            if any(term in low for term in ("error", "exception", "warning", "rejected")):
                errors.append(line[-240:])
    return bool(heartbeat), heartbeat, errors[-20:]


def nearest_by_date(rows: list[dict[str, str]], date: str) -> dict[str, str]:
    if not rows:
        return {}
    exact = [r for r in rows if r.get("date") == date]
    if exact:
        return exact[-1]
    prior = [r for r in rows if r.get("date", "") <= date]
    return prior[-1] if prior else rows[-1]


def context_for(pair: str, signal_time: str) -> dict[str, Any]:
    date = (signal_time or now())[:10]
    market = nearest_by_date(read_csv(MARKET_HISTORY), date)
    latest = load_json(MARKET_LATEST, {})
    if not market:
        market = latest
    pair_rows = [r for r in read_csv(PAIR_QUALITY) if r.get("pair") == pair]
    pairq = nearest_by_date(pair_rows, date)
    return {
        "market_sentiment_score": as_float(market.get("market_sentiment_score", latest.get("market_sentiment_score", 50)), 50),
        "primary_regime": market.get("primary_regime", latest.get("primary_regime", "")),
        "regime_tags": market.get("regime_tags", latest.get("regime_tags", "")),
        "btc_trend_score": as_float(market.get("btc_trend_score"), 50),
        "market_breadth_score": as_float(market.get("market_breadth_score"), 50),
        "volatility_score": as_float(market.get("volatility_score"), 50),
        "pair_quality_score": as_float(pairq.get("pair_quality_score"), 50),
        "volume_zscore": as_float(pairq.get("volume_zscore"), 0),
        "pair_atr_percent": as_float(pairq.get("pair_atr_percent"), 0),
        "pair_relative_strength_score": as_float(pairq.get("pair_relative_strength_score"), 50),
        "pair_return_1d": as_float(pairq.get("pair_return_1d"), 0),
    }


def v2_params() -> dict[str, float]:
    summary = load_json(V2_SUMMARY, {})
    return summary.get("best_params") or {
        "allow_full_threshold": 65,
        "allow_half_threshold": 50,
        "allow_quarter_threshold": 35,
        "pair_quality_min_hard_block": 20,
        "atr_block_threshold": 12.63683,
        "volume_zscore_block_threshold": 3,
        "risk_score_weight": 0.8,
        "opportunity_score_weight": 1.2,
    }


def v2_decision(ctx: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    sentiment = as_float(ctx.get("market_sentiment_score"), 50)
    pq = as_float(ctx.get("pair_quality_score"), 50)
    vz = abs(as_float(ctx.get("volume_zscore"), 0))
    atr = as_float(ctx.get("pair_atr_percent"), 0)
    breadth = as_float(ctx.get("market_breadth_score"), 50)
    vol_score = as_float(ctx.get("volatility_score"), 50)
    btc_trend = as_float(ctx.get("btc_trend_score"), 50)
    rel = as_float(ctx.get("pair_relative_strength_score"), 50)
    regime = str(ctx.get("primary_regime") or "")
    tags = str(ctx.get("regime_tags") or "")
    pair_ret_1d = as_float(ctx.get("pair_return_1d"), 0)
    reasons: list[str] = []
    risk = max(0, 50 - btc_trend) * 0.35
    risk += max(0, 50 - breadth) * 0.30
    risk += max(0, 50 - vol_score) * 0.25
    risk += max(0, atr - 6) * 3.0
    risk += max(0, vz - 3) * 8.0
    risk += max(0, 45 - sentiment) * 0.30
    if "risk_off" in tags:
        risk += 8
        reasons.append("risk_off")
    if regime == "panic":
        risk += 12
        reasons.append("panic")
    if regime == "overheated":
        risk += 8
        reasons.append("overheated")
    if pair_ret_1d < -8:
        risk += 10
        reasons.append("pair_1d_drop")
    opportunity = pq * 0.35
    opportunity += rel * 0.15
    opportunity += max(0, sentiment - 30) * 0.10
    opportunity += 5 if regime not in ("panic", "risk_off") else 0
    hard = ""
    if pq < as_float(params.get("pair_quality_min_hard_block"), 20):
        hard = "hard_pair_quality"
    elif regime == "panic" and btc_trend < 30 and breadth < 30:
        hard = "panic_btc_crash_breadth_bad"
    elif atr >= as_float(params.get("atr_block_threshold"), 12.63683) and vz >= as_float(params.get("volume_zscore_block_threshold"), 3) and pair_ret_1d <= -8:
        hard = "extreme_atr_volume_return"
    final = max(0, min(100, opportunity * as_float(params.get("opportunity_score_weight"), 1.2) - risk * as_float(params.get("risk_score_weight"), 0.8) + 50))
    if hard:
        decision, mult, reason = "block", 0.0, hard
    elif final >= as_float(params.get("allow_full_threshold"), 65):
        decision, mult, reason = "allow_full", 1.0, "score_full"
    elif final >= as_float(params.get("allow_half_threshold"), 50):
        decision, mult, reason = "reduce_stake", 0.5, "score_half"
    elif final >= as_float(params.get("allow_quarter_threshold"), 35):
        decision, mult, reason = "reduce_stake", 0.25, "score_quarter"
    else:
        decision, mult, reason = "block", 0.0, "score_below_quarter"
    if reasons:
        reason += ":" + ",".join(reasons)
    return {"candidate_decision": decision, "stake_multiplier": mult, "decision_reason": reason, "risk_score": risk, "opportunity_score": opportunity, "final_score": final}


def candidate_decision(name: str, ctx: dict[str, Any]) -> dict[str, Any]:
    if name == "baseline_nfi":
        return {"candidate_decision": "allow_full", "stake_multiplier": 1.0, "decision_reason": "baseline_no_filter"}
    if name == "decision_engine_v2_frozen":
        return v2_decision(ctx, v2_params())
    if name == "decision_engine_v2_relaxed":
        dec = v2_decision(ctx, v2_params())
        reason = str(dec["decision_reason"])
        pq = as_float(ctx.get("pair_quality_score"), 50)
        if reason == "hard_pair_quality" and 20 <= pq < 40:
            dec.update({"candidate_decision": "reduce_stake", "stake_multiplier": 0.25, "decision_reason": "relaxed_pair_quality_reduce"})
        elif "extreme_atr_volume_return" in reason:
            dec.update({"candidate_decision": "reduce_stake", "stake_multiplier": 0.25, "decision_reason": "relaxed_extreme_atr_volume_reduce"})
        return dec
    if name == "sizing_only":
        pq = as_float(ctx.get("pair_quality_score"), 50)
        vz = abs(as_float(ctx.get("volume_zscore"), 0))
        atr = as_float(ctx.get("pair_atr_percent"), 0)
        regime = str(ctx.get("primary_regime") or "")
        btc = as_float(ctx.get("btc_trend_score"), 50)
        breadth = as_float(ctx.get("market_breadth_score"), 50)
        if pq < 20:
            return {"candidate_decision": "block", "stake_multiplier": 0.0, "decision_reason": "sizing_hard_pair_quality"}
        if regime == "panic" and btc < 25 and breadth < 25:
            return {"candidate_decision": "block", "stake_multiplier": 0.0, "decision_reason": "sizing_extreme_panic"}
        mult = 1.0
        reasons = []
        if pq < 40:
            mult *= 0.5
            reasons.append("pair_quality_reduce")
        if regime in ("panic", "fear") or "risk_off" in str(ctx.get("regime_tags") or ""):
            mult *= 0.5
            reasons.append("risk_regime_reduce")
        if atr > 12 or vz > 5:
            mult *= 0.5
            reasons.append("volatility_reduce")
        if mult >= 0.75:
            decision = "allow_full"
        else:
            decision = "reduce_stake"
        return {"candidate_decision": decision, "stake_multiplier": round(max(0.125, mult), 6), "decision_reason": "+".join(reasons) or "sizing_full"}
    raise ValueError(name)


def classify_consistency(candidate: str, decision: str, has_trade: bool, event_type: str, signal_status: str) -> str:
    if event_type == "heartbeat":
        if signal_status == "confirmed_no_signal":
            return "confirmed_no_signal_no_trade"
        if signal_status == "data_unavailable":
            return "data_unavailable"
        return "signal_unknown_no_trade"
    if event_type == "signal_replay":
        return "confirmed_signal_with_trade" if has_trade else "confirmed_signal_no_trade"
    allow = decision != "block"
    if signal_status == "inferred_from_trade":
        return "inferred_trade_without_signal_replay"
    if candidate == "baseline_nfi":
        return "consistent" if has_trade else "no_new_signal_or_trade"
    if not allow and has_trade:
        return "shadow_blocked_actual_trade"
    if allow and not has_trade:
        return "shadow_allowed_no_trade"
    if allow and has_trade:
        return "consistent"
    return "inconclusive"


def current_profit(trade: dict[str, Any]) -> float:
    return as_float(trade.get("close_profit"), 0)


def closed_trade_transitions(
    trades: list[dict[str, Any]],
    previous_trade_states: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        trade
        for trade in trades
        if str(trade.get("id")) in previous_trade_states
        and previous_trade_states[str(trade.get("id"))].get("is_open") is True
        and not trade.get("is_open")
    ]


def build_events(log: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    trades = read_db_trades()
    orders = read_db_orders()
    signal_snapshot = load_json(SIGNAL_SNAPSHOT, {})
    previous = load_json(SNAPSHOT, {})
    previous_trade_ids = {str(x) for x in previous.get("seen_trade_ids", [])}
    previous_trade_states = previous.get("trade_states", {})
    new_trades = [t for t in trades if str(t.get("id")) not in previous_trade_ids]
    if not new_trades and trades:
        new_trades = []
    closed_transitions = closed_trade_transitions(trades, previous_trade_states)
    events: list[dict[str, Any]] = []
    for trade in new_trades:
        events.append({
            "event_type": "dry_run_trade",
            "pair": trade.get("pair") or "",
            "signal_time": trade.get("open_date") or "",
            "trade_open_time": trade.get("open_date") or "",
            "enter_tag": trade.get("enter_tag") or "",
            "dry_run_trade_created": True,
            "dry_run_trade_id": trade.get("id") or "",
            "dry_run_open_rate": trade.get("open_rate") or "",
            "dry_run_current_profit": current_profit(trade),
            "dry_run_close_profit": trade.get("close_profit") if not trade.get("is_open") else "",
            "raw_trade": trade,
        })
    for trade in closed_transitions:
        events.append({
            "event_type": "dry_run_trade_closed",
            "pair": trade.get("pair") or "",
            "signal_time": trade.get("open_date") or "",
            "trade_open_time": trade.get("open_date") or "",
            "enter_tag": trade.get("enter_tag") or "",
            "dry_run_trade_created": True,
            "dry_run_trade_id": trade.get("id") or "",
            "dry_run_open_rate": trade.get("open_rate") or "",
            "dry_run_current_profit": current_profit(trade),
            "dry_run_close_profit": trade.get("close_profit"),
            "raw_trade": trade,
        })
    confirmed_signals = signal_snapshot.get("confirmed_signals") or {}
    if not events and signal_snapshot.get("signal_detection_status") == "confirmed_signal":
        for pair, signal in confirmed_signals.items():
            events.append({
                "event_type": "signal_replay",
                "pair": pair,
                "signal_time": signal.get("signal_time") or signal_snapshot.get("generated_at") or "",
                "trade_open_time": "",
                "enter_tag": signal.get("enter_tag") or "",
                "dry_run_trade_created": False,
                "dry_run_trade_id": "",
                "dry_run_open_rate": "",
                "dry_run_current_profit": "",
                "dry_run_close_profit": "",
                "raw_trade": {},
            })
    if not events:
        events.append({
            "event_type": "heartbeat",
            "pair": "",
            "signal_time": "",
            "trade_open_time": "",
            "enter_tag": "",
            "dry_run_trade_created": False,
            "dry_run_trade_id": "",
            "dry_run_open_rate": "",
            "dry_run_current_profit": "",
            "dry_run_close_profit": "",
            "raw_trade": {},
        })
    status = {
        "trades": trades,
        "orders": orders,
        "new_trade_count": len(new_trades),
        "open_trades_count": sum(1 for t in trades if t.get("is_open")),
        "recent_closed_trades": [t for t in trades if not t.get("is_open")][-10:],
        "signal_detection_status": signal_snapshot.get("signal_detection_status") or ("inferred_from_trade" if new_trades else "data_unavailable"),
        "signal_check_method": signal_snapshot.get("signal_check_method", ""),
        "confirmed_signal_count": signal_snapshot.get("confirmed_signal_count", 0),
        "confirmed_no_signal_count": signal_snapshot.get("confirmed_no_signal_count", 0),
        "inferred_signal_count": signal_snapshot.get("inferred_signal_count", len(new_trades)),
        "signal_check_notes": signal_snapshot.get("notes", ""),
    }
    log.append(f"trades_total={len(trades)} new_trades={len(new_trades)} orders={len(orders)}")
    return events, status


def build_rows(events: list[dict[str, Any]], signal_status: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    snap_time = now()
    for event in events:
        ctx = context_for(str(event.get("pair") or ""), str(event.get("signal_time") or ""))
        for candidate in CANDIDATES:
            dec = candidate_decision(candidate, ctx)
            consistency = classify_consistency(candidate, dec["candidate_decision"], bool(event.get("dry_run_trade_created")), str(event.get("event_type")), str(signal_status.get("signal_detection_status", "")))
            rows.append({
                "snapshot_time": snap_time,
                "event_type": event.get("event_type"),
                "pair": event.get("pair"),
                "signal_time": event.get("signal_time"),
                "trade_open_time": event.get("trade_open_time"),
                "enter_tag": event.get("enter_tag"),
                "market_sentiment_score": ctx.get("market_sentiment_score"),
                "primary_regime": ctx.get("primary_regime"),
                "regime_tags": ctx.get("regime_tags"),
                "pair_quality_score": ctx.get("pair_quality_score"),
                "volume_zscore": ctx.get("volume_zscore"),
                "pair_atr_percent": ctx.get("pair_atr_percent"),
                "candidate_name": candidate,
                "candidate_decision": dec["candidate_decision"],
                "stake_multiplier": dec["stake_multiplier"],
                "decision_reason": dec["decision_reason"],
                "dry_run_trade_created": event.get("dry_run_trade_created"),
                "dry_run_trade_id": event.get("dry_run_trade_id"),
                "dry_run_open_rate": event.get("dry_run_open_rate"),
                "dry_run_current_profit": event.get("dry_run_current_profit"),
                "dry_run_close_profit": event.get("dry_run_close_profit"),
                "consistency_status": consistency,
                "signal_detection_status": signal_status.get("signal_detection_status", ""),
                "signal_check_method": signal_status.get("signal_check_method", ""),
                "confirmed_signal_count": signal_status.get("confirmed_signal_count", 0),
                "confirmed_no_signal_count": signal_status.get("confirmed_no_signal_count", 0),
                "inferred_signal_count": signal_status.get("inferred_signal_count", 0),
                "signal_check_notes": signal_status.get("signal_check_notes", ""),
                "notes": "shadow-only; does not affect dry-run orders",
            })
    return rows


def max_drawdown(values: list[float]) -> float:
    equity = peak = dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dd


def aggregate_outputs(all_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    comparison: list[dict[str, Any]] = []
    consistency_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        rows = [r for r in all_rows if r.get("candidate_name") == candidate]
        event_rows = [r for r in rows if r.get("event_type") in ("dry_run_trade", "signal_replay")]
        outcome_rows = [
            r
            for r in rows
            if r.get("event_type") == "dry_run_trade_closed"
            or r.get("dry_run_close_profit") not in ("", None)
        ]
        allowed = [r for r in event_rows if r.get("candidate_decision") != "block"]
        blocked = [r for r in event_rows if r.get("candidate_decision") == "block"]
        reduced = [r for r in event_rows if r.get("candidate_decision") == "reduce_stake"]
        full = [r for r in event_rows if r.get("candidate_decision") == "allow_full"]
        trade_rows = [r for r in event_rows if str(r.get("dry_run_trade_created")).lower() == "true"]
        allowed_trade = [r for r in trade_rows if r.get("candidate_decision") != "block"]
        blocked_trade = [r for r in trade_rows if r.get("candidate_decision") == "block"]
        allowed_outcomes = [r for r in outcome_rows if r.get("candidate_decision") != "block"]
        blocked_outcomes = [r for r in outcome_rows if r.get("candidate_decision") == "block"]
        allowed_profit = sum(as_float(r.get("dry_run_close_profit")) for r in allowed_outcomes)
        blocked_profit = sum(as_float(r.get("dry_run_close_profit")) for r in blocked_outcomes)
        missed_profit = sum(as_float(r.get("dry_run_close_profit")) for r in blocked_outcomes if as_float(r.get("dry_run_close_profit")) > 0)
        avoided_loss = abs(sum(as_float(r.get("dry_run_close_profit")) for r in blocked_outcomes if as_float(r.get("dry_run_close_profit")) < 0))
        closed_allowed = [as_float(r.get("dry_run_close_profit")) - (SLIPPAGE_PER_SIDE * 2) for r in allowed_outcomes]
        consistency_good = [r for r in rows if r.get("consistency_status") == "consistent"]
        consistency_known = [r for r in rows if r.get("consistency_status") not in ("no_new_signal_or_trade", "inconclusive", "data_unavailable")]
        comparison.append({
            "candidate_name": candidate,
            "observed_events": len(event_rows),
            "allowed_events": len(allowed),
            "blocked_events": len(blocked),
            "reduced_stake_events": len(reduced),
            "full_stake_events": len(full),
            "trades_that_would_be_allowed": len(allowed_trade),
            "trades_that_would_be_blocked": len(blocked_trade),
            "closed_trade_profit_allowed": round(allowed_profit, 8),
            "closed_trade_profit_blocked": round(blocked_profit, 8),
            "missed_profit": round(missed_profit, 8),
            "avoided_loss": round(avoided_loss, 8),
            "net_filter_value": round(avoided_loss - missed_profit, 8),
            "win_rate_allowed": round(sum(1 for p in closed_allowed if p > 0) / len(closed_allowed), 6) if closed_allowed else "",
            "max_drawdown_estimate": round(max_drawdown(closed_allowed), 8) if closed_allowed else "",
            "consistency_rate": round(len(consistency_good) / len(consistency_known), 6) if consistency_known else "",
            "notes": "insufficient_observation_window" if len(event_rows) < 20 else "",
        })
        statuses = sorted({r.get("consistency_status") or "unknown" for r in rows})
        for status in statuses:
            consistency_rows.append({"candidate_name": candidate, "consistency_status": status, "count": sum(1 for r in rows if (r.get("consistency_status") or "unknown") == status)})
        for r in blocked_outcomes:
            profit = as_float(r.get("dry_run_close_profit"))
            blocked_rows.append({**r, "missed_profit": profit if profit > 0 else 0, "avoided_loss": abs(profit) if profit < 0 else 0})
    return comparison, consistency_rows, blocked_rows


def write_prelive_update(summary: dict[str, Any], comparison: list[dict[str, Any]]) -> None:
    by_name = {r["candidate_name"]: r for r in comparison}
    lines = [
        "# Pre-Live Gate Shadow Evidence Update",
        "",
        "LIVE TRADING STATUS: BLOCKED",
        "",
        f"- Dry-run observation days: `{summary['observation_days']}`.",
        f"- Shadow sample events: `{summary['observed_events']}`.",
        f"- New trade since last snapshot: `{summary['new_trade_since_last_snapshot']}`.",
        f"- Signal detection status: `{summary['signal_detection_status']}`.",
        f"- v2_frozen net filter value: `{by_name.get('decision_engine_v2_frozen', {}).get('net_filter_value', '')}`.",
        f"- v2_relaxed net filter value: `{by_name.get('decision_engine_v2_relaxed', {}).get('net_filter_value', '')}`.",
        f"- sizing_only net filter value: `{by_name.get('sizing_only', {}).get('net_filter_value', '')}`.",
        f"- Dry-run consistency evidence: `{summary['consistency_status']}`.",
        f"- 2-4 week observation met: `{summary['observation_days'] >= 14}`.",
        f"- Forward closed trades: `{summary['forward_closed_trades']}`.",
        f"- Out-of-sample forward sample met: `{summary['forward_closed_trades'] >= 20}`.",
        "",
        "Pre-live gate remains BLOCKED unless every hard gate is satisfied.",
    ]
    PRELIVE_UPDATE.parent.mkdir(parents=True, exist_ok=True)
    PRELIVE_UPDATE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    REPORT_OUT.mkdir(parents=True, exist_ok=True)
    USER_OUT.mkdir(parents=True, exist_ok=True)
    log: list[str] = [f"generated_at={now()}", f"project={PROJECT_ROOT}"]
    before = RUNTIME_CONFIG.read_bytes() if RUNTIME_CONFIG.exists() else b""
    safe = safety_check()
    if not safe["pass"]:
        SUMMARY.write_text(json.dumps({"safe_config": False, "safety_checks": safe["checks"], "pre_live_gate_status": "BLOCKED"}, indent=2), encoding="utf-8")
        LOGS.write_text("BLOCKED: unsafe runtime config\n" + json.dumps(safe["checks"], indent=2) + "\n", encoding="utf-8")
        print("[BLOCKED] unsafe runtime config")
        return 2
    api_status = read_freqtrade_status(safe["config"])
    log_running, heartbeat, recent_errors = bot_running_from_logs()
    events, runtime_status = build_events(log)
    rows = build_rows(events, runtime_status)
    append_csv(JOURNAL, rows, JOURNAL_FIELDS)
    all_rows = read_csv(JOURNAL)
    comparison, consistency_rows, blocked_rows = aggregate_outputs(all_rows)
    write_csv(COMPARISON, comparison)
    write_csv(CONSISTENCY, consistency_rows)
    write_csv(BLOCKED, blocked_rows)
    dates = sorted({(r.get("snapshot_time") or "")[:10] for r in all_rows if r.get("snapshot_time")})
    observed_events = sum(
        1
        for r in all_rows
        if r.get("event_type") in ("dry_run_trade", "signal_replay")
        and r.get("candidate_name") == "baseline_nfi"
    )
    forward_closed_trade_ids = {
        str(r.get("dry_run_trade_id") or f"{r.get('pair')}|{r.get('signal_time')}")
        for r in all_rows
        if r.get("candidate_name") == "baseline_nfi"
        and (
            r.get("event_type") == "dry_run_trade_closed"
            or r.get("dry_run_close_profit") not in ("", None)
        )
    }
    consistency_status = "no_new_signal_or_trade" if not observed_events else "inconclusive"
    if runtime_status["signal_detection_status"] == "confirmed_no_signal" and not observed_events:
        consistency_status = "confirmed_no_signal_no_trade"
    elif runtime_status["signal_detection_status"] == "confirmed_signal" and not runtime_status["new_trade_count"]:
        consistency_status = "confirmed_signal_no_trade"
    elif runtime_status["signal_detection_status"] == "inferred_from_trade":
        consistency_status = "inferred_trade_without_signal_replay"
    elif runtime_status["signal_detection_status"] == "data_unavailable":
        consistency_status = "data_unavailable"
    if any(r.get("consistency_status") == "shadow_blocked_actual_trade" for r in all_rows):
        consistency_status = "shadow_blocked_actual_trade"
    latest = load_json(MARKET_LATEST, {})
    summary = {
        "generated_at": now(),
        "safe_config": True,
        "safety_checks": safe["checks"],
        "runtime_config_untouched": before == (RUNTIME_CONFIG.read_bytes() if RUNTIME_CONFIG.exists() else b""),
        "candidates_config": str(CANDIDATES_CONFIG),
        "candidates": CANDIDATES,
        "bot_running": bool(api_status["api_available"] or log_running),
        "api_available": api_status["api_available"],
        "open_trades_count": runtime_status["open_trades_count"],
        "recent_closed_trades_count": len(runtime_status["recent_closed_trades"]),
        "recent_orders_count": len(runtime_status["orders"]),
        "new_trade_since_last_snapshot": runtime_status["new_trade_count"],
        "new_signal_since_last_snapshot": 0,
        "signal_detection_status": runtime_status["signal_detection_status"],
        "signal_check_method": runtime_status["signal_check_method"],
        "confirmed_signal_count": runtime_status["confirmed_signal_count"],
        "confirmed_no_signal_count": runtime_status["confirmed_no_signal_count"],
        "inferred_signal_count": runtime_status["inferred_signal_count"],
        "signal_check_notes": runtime_status["signal_check_notes"],
        "current_profit": (api_status.get("data", {}).get("profit") or {}).get("profit_all_ratio", ""),
        "wallet_state_available": "balance" in api_status.get("data", {}),
        "last_bot_heartbeat": heartbeat,
        "recent_errors_count": len(recent_errors),
        "recent_errors": recent_errors,
        "today_market_regime": latest.get("primary_regime", ""),
        "today_market_sentiment_score": latest.get("market_sentiment_score", ""),
        "observation_days": len(dates),
        "observed_events": observed_events,
        "forward_closed_trades": len(forward_closed_trade_ids),
        "consistency_status": consistency_status,
        "pre_live_gate_status": "BLOCKED",
        "candidate_comparison": comparison,
        "notes": "Shadow decisions are read-only and do not affect Freqtrade dry-run.",
    }
    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    SNAPSHOT.write_text(json.dumps({
        "snapshot_time": summary["generated_at"],
        "seen_trade_ids": [str(t.get("id")) for t in runtime_status["trades"]],
        "trade_states": {
            str(t.get("id")): {
                "is_open": bool(t.get("is_open")),
                "close_profit": t.get("close_profit"),
            }
            for t in runtime_status["trades"]
        },
        "open_trades_count": runtime_status["open_trades_count"],
        "observed_events": observed_events,
        "signal_detection_status": runtime_status["signal_detection_status"],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    write_prelive_update(summary, comparison)
    log += [
        f"api_available={api_status['api_available']}",
        f"bot_running={summary['bot_running']}",
        f"events_this_run={len(events)}",
        f"rows_appended={len(rows)}",
        f"signal_detection_status={runtime_status['signal_detection_status']}",
        f"runtime_config_untouched={summary['runtime_config_untouched']}",
        f"journal={JOURNAL}",
        f"summary={SUMMARY}",
    ]
    LOGS.write_text("\n".join(log) + "\n", encoding="utf-8")
    for line in log:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
