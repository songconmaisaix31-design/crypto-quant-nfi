#!/usr/bin/env python3
from __future__ import annotations

import base64
import csv
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
V2_RULES = PROJECT_ROOT / "configs/decision_engine_v2_rules.yaml"
V2_SUMMARY = PROJECT_ROOT / "reports/decision_engine_v2/decision_engine_v2_summary.json"
MARKET_LATEST = PROJECT_ROOT / "user_data/market_state/market_state_latest.json"
MARKET_HISTORY = PROJECT_ROOT / "user_data/market_state/market_state_history.csv"
PAIR_QUALITY = PROJECT_ROOT / "reports/market_state/pair_quality_scores.csv"
DRYRUN_DB = PROJECT_ROOT / "user_data/tradesv3.dryrun.sqlite"
LOG_DIR = PROJECT_ROOT / "user_data/logs"
USER_OUT = PROJECT_ROOT / "user_data/decision_engine_shadow"
REPORT_OUT = PROJECT_ROOT / "reports/decision_engine_shadow"
FROZEN_RULES = USER_OUT / "frozen_v2_rules.yaml"
FROZEN_META = USER_OUT / "frozen_v2_metadata.json"
JOURNAL = REPORT_OUT / "shadow_decision_journal.csv"
OUTCOMES = REPORT_OUT / "shadow_trade_outcomes.csv"
CONSISTENCY = REPORT_OUT / "shadow_consistency_matrix.csv"
LOGS = REPORT_OUT / "shadow_logs.txt"
SLIPPAGE_PER_SIDE = 0.0005

JOURNAL_FIELDS = [
    "journal_time",
    "rule_version",
    "config_hash",
    "bot_running",
    "dry_run",
    "pair",
    "signal_time",
    "enter_tag",
    "market_sentiment_score",
    "primary_regime",
    "regime_tags",
    "pair_quality_score",
    "risk_score",
    "opportunity_score",
    "final_score",
    "v2_decision",
    "stake_multiplier",
    "v2_reason",
    "actual_dry_run_action",
    "actual_trade_id",
    "consistency_status",
    "observation_status",
    "notes",
]

OUTCOME_FIELDS = [
    "actual_trade_id",
    "pair",
    "open_date",
    "close_date",
    "enter_tag",
    "v2_decision_at_open",
    "v2_score_at_open",
    "profit_abs",
    "profit_ratio",
    "duration",
    "would_v2_have_allowed",
    "would_v2_have_blocked",
    "v2_outcome_label",
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


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def append_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    return {"checks": checks, "pass": all(checks.values()), "config": cfg}


def freeze_v2_rules(log: list[str]) -> dict[str, Any]:
    USER_OUT.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.mkdir(parents=True, exist_ok=True)
    if not V2_RULES.exists():
        raise RuntimeError(f"Missing v2 rules file: {V2_RULES}")
    created = False
    if not FROZEN_RULES.exists():
        shutil.copy2(V2_RULES, FROZEN_RULES)
        created = True
        log.append(f"created frozen rules: {FROZEN_RULES}")
    current_hash = sha256(V2_RULES)
    frozen_hash = sha256(FROZEN_RULES)
    v2_summary = load_json(V2_SUMMARY, {})
    meta = load_json(FROZEN_META, {})
    if not meta:
        meta = {
            "rule_version": "decision_engine_v2_shadow_001",
            "frozen_at": now(),
            "source_rules": str(V2_RULES),
            "frozen_rules": str(FROZEN_RULES),
            "config_hash": frozen_hash,
            "source_config_hash_at_freeze": current_hash,
            "v2_core_metrics": {
                "allowed_signals_ratio": v2_summary.get("v2_allowed_signals_ratio"),
                "net_filter_value": v2_summary.get("v2_net_filter_value"),
                "slippage_after_profit": (v2_summary.get("v2_all") or {}).get("total_profit_after_slippage"),
                "max_drawdown": (v2_summary.get("v2_all") or {}).get("max_drawdown"),
                "train_rows": v2_summary.get("train_rows"),
                "test_rows": v2_summary.get("test_rows"),
                "split_mode": v2_summary.get("split_mode"),
            },
            "best_params": v2_summary.get("best_params") or {},
            "notes": "Frozen for shadow observation only. This file does not enable live trading.",
        }
        FROZEN_META.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        log.append(f"created frozen metadata: {FROZEN_META}")
    else:
        meta["current_source_config_hash"] = current_hash
        meta["frozen_config_hash"] = frozen_hash
        meta["source_matches_frozen"] = current_hash == frozen_hash
        FROZEN_META.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    if created:
        log.append(f"frozen config hash: {frozen_hash}")
    return meta


def api_request(cfg: dict[str, Any], endpoint: str, timeout: float = 2.0) -> tuple[bool, Any, str]:
    api = cfg.get("api_server", {})
    host = api.get("listen_ip_address") or "127.0.0.1"
    port = api.get("listen_port") or 8080
    url = f"http://{host}:{port}{endpoint}"
    request = urllib.request.Request(url)
    username = api.get("username")
    password = api.get("password")
    if username and password:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
            try:
                return True, json.loads(text), ""
            except json.JSONDecodeError:
                return True, text, ""
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}"


def read_api_status(cfg: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"available": False, "errors": {}, "data": {}}
    for name, endpoint in {
        "ping": "/api/v1/ping",
        "status": "/api/v1/status",
        "count": "/api/v1/count",
        "profit": "/api/v1/profit",
    }.items():
        ok, data, err = api_request(cfg, endpoint)
        if ok:
            result["available"] = True
            result["data"][name] = data
        else:
            result["errors"][name] = err
    return result


def read_db_trades() -> list[dict[str, Any]]:
    if not DRYRUN_DB.exists():
        return []
    con = sqlite3.connect(DRYRUN_DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = cur.execute("select * from trades order by open_date asc, id asc").fetchall()
    return [dict(row) for row in rows]


def read_db_counts() -> dict[str, Any]:
    out = {"db_exists": DRYRUN_DB.exists(), "trade_count": 0, "order_count": 0, "error": ""}
    if not DRYRUN_DB.exists():
        return out
    try:
        con = sqlite3.connect(DRYRUN_DB)
        cur = con.cursor()
        out["trade_count"] = int(cur.execute("select count(*) from trades").fetchone()[0])
        out["order_count"] = int(cur.execute("select count(*) from orders").fetchone()[0])
    except Exception as exc:
        out["error"] = repr(exc)
    return out


def bot_running_from_logs() -> bool:
    candidates = sorted(LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates[:4]:
        text = path.read_text(encoding="utf-8", errors="ignore")[-20000:].lower()
        if "freqtradebot is running" in text or "bot heartbeat" in text or "state changed to: running" in text:
            return True
    return False


def nearest_by_date(rows: list[dict[str, str]], date: str, keys: tuple[str, ...] = ()) -> dict[str, str]:
    if not rows:
        return {}
    exact = [r for r in rows if r.get("date") == date and all(r.get(k) for k in keys)]
    if exact:
        return exact[-1]
    dated = [r for r in rows if r.get("date", "") <= date]
    return dated[-1] if dated else rows[-1]


def context_for(pair: str, signal_time: str) -> dict[str, Any]:
    date = (signal_time or now())[:10]
    market_history = read_csv(MARKET_HISTORY)
    pair_quality = read_csv(PAIR_QUALITY)
    market = nearest_by_date(market_history, date)
    pair_rows = [r for r in pair_quality if r.get("pair") == pair]
    pair_row = nearest_by_date(pair_rows, date)
    latest = load_json(MARKET_LATEST, {})
    if not market:
        market = latest
    return {
        "market_sentiment_score": as_float(market.get("market_sentiment_score", latest.get("market_sentiment_score", 50)), 50),
        "primary_regime": market.get("primary_regime", latest.get("primary_regime", "")),
        "regime_tags": market.get("regime_tags", latest.get("regime_tags", "")),
        "btc_trend_score": as_float(market.get("btc_trend_score"), 50),
        "market_breadth_score": as_float(market.get("market_breadth_score"), 50),
        "volatility_score": as_float(market.get("volatility_score"), 50),
        "pair_quality_score": as_float(pair_row.get("pair_quality_score"), 50),
        "pair_relative_strength_score": as_float(pair_row.get("pair_relative_strength_score"), 50),
        "pair_return_1d": as_float(pair_row.get("pair_return_1d"), 0),
        "pair_atr_percent": as_float(pair_row.get("pair_atr_percent"), 0),
        "volume_zscore": as_float(pair_row.get("volume_zscore"), 0),
    }


def decide_v2(ctx: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
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
    risk = 0.0
    risk += max(0, 50 - btc_trend) * 0.35
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
    opportunity = 0.0
    opportunity += pq * 0.35
    opportunity += rel * 0.15
    opportunity += max(0, sentiment - 30) * 0.10
    opportunity += 5 if regime not in ("panic", "risk_off") else 0
    pq_min = as_float(params.get("pair_quality_min_hard_block"), 20)
    atr_block = as_float(params.get("atr_block_threshold"), 12.63683)
    vz_block = as_float(params.get("volume_zscore_block_threshold"), 3)
    hard = ""
    if pq < pq_min:
        hard = "hard_pair_quality"
    elif regime == "panic" and btc_trend < 30 and breadth < 30:
        hard = "panic_btc_crash_breadth_bad"
    elif atr >= atr_block and vz >= vz_block and pair_ret_1d <= -8:
        hard = "extreme_atr_volume_return"
    final = max(0, min(100, opportunity * as_float(params.get("opportunity_score_weight"), 1.2) - risk * as_float(params.get("risk_score_weight"), 0.8) + 50))
    if hard:
        decision = "block"
        mult = 0.0
        reason = hard
    elif final >= as_float(params.get("allow_full_threshold"), 65):
        decision = "allow_full"
        mult = 1.0
        reason = "score_full"
    elif final >= as_float(params.get("allow_half_threshold"), 50):
        decision = "allow_half"
        mult = 0.5
        reason = "score_half"
    elif final >= as_float(params.get("allow_quarter_threshold"), 35):
        decision = "allow_quarter"
        mult = 0.25
        reason = "score_quarter"
    else:
        decision = "block"
        mult = 0.0
        reason = "score_below_quarter"
    if reasons:
        reason += ":" + ",".join(reasons)
    return {
        "risk_score": round(risk, 6),
        "opportunity_score": round(opportunity, 6),
        "final_score": round(final, 6),
        "v2_decision": decision,
        "stake_multiplier": mult,
        "v2_reason": reason,
        "allow": mult > 0,
    }


def parse_dt(value: Any) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo:
            parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def minutes_between(start: Any, end: Any) -> str:
    s = parse_dt(start)
    e = parse_dt(end)
    if not s or not e:
        return ""
    return str(round((e - s).total_seconds() / 60, 4))


def build_rows(meta: dict[str, Any], safety: dict[str, Any], api_status: dict[str, Any], log: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    params = meta.get("best_params") or {}
    rule_version = meta.get("rule_version", "decision_engine_v2_shadow_001")
    config_hash = meta.get("config_hash") or sha256(FROZEN_RULES)
    dry_run = safety["checks"]["dry_run"]
    trades = read_db_trades()
    db_counts = read_db_counts()
    bot_running = api_status.get("available") or bot_running_from_logs()
    log.append(f"api_available={api_status.get('available')} db_counts={db_counts}")
    existing = read_csv(JOURNAL)
    seen = {(r.get("actual_trade_id"), r.get("signal_time"), r.get("pair")) for r in existing if r.get("actual_trade_id") or r.get("pair")}
    journal_rows: list[dict[str, Any]] = []
    outcome_rows: list[dict[str, Any]] = []
    for trade in trades:
        pair = str(trade.get("pair") or "")
        signal_time = str(trade.get("open_date") or "")
        trade_id = str(trade.get("id") or "")
        ctx = context_for(pair, signal_time)
        dec = decide_v2(ctx, params)
        action = "dry_run_open" if trade.get("is_open") else "dry_run_closed"
        if dec["allow"]:
            status = "v2_allow_and_dry_run_opened"
        else:
            status = "v2_block_but_dry_run_opened"
        key = (trade_id, signal_time, pair)
        if key not in seen:
            journal_rows.append({
                "journal_time": now(),
                "rule_version": rule_version,
                "config_hash": config_hash,
                "bot_running": bot_running,
                "dry_run": dry_run,
                "pair": pair,
                "signal_time": signal_time,
                "enter_tag": trade.get("enter_tag") or "",
                **ctx,
                **{k: dec[k] for k in ("risk_score", "opportunity_score", "final_score", "v2_decision", "stake_multiplier", "v2_reason")},
                "actual_dry_run_action": action,
                "actual_trade_id": trade_id,
                "consistency_status": status,
                "observation_status": "observed_dry_run_trade",
                "notes": "Shadow observation only; no order control.",
            })
        close_date = trade.get("close_date") or ""
        profit_abs = as_float(trade.get("close_profit_abs"), 0)
        profit_ratio = as_float(trade.get("close_profit"), 0)
        if trade.get("is_open"):
            label = "pending"
        elif dec["allow"] and profit_ratio > 0:
            label = "correct_allow_winner"
        elif dec["allow"] and profit_ratio <= 0:
            label = "wrong_allow_loser"
        elif (not dec["allow"]) and profit_ratio <= 0:
            label = "correct_block_loser"
        else:
            label = "wrong_block_winner"
        outcome_rows.append({
            "actual_trade_id": trade_id,
            "pair": pair,
            "open_date": signal_time,
            "close_date": close_date,
            "enter_tag": trade.get("enter_tag") or "",
            "v2_decision_at_open": dec["v2_decision"],
            "v2_score_at_open": dec["final_score"],
            "profit_abs": profit_abs,
            "profit_ratio": profit_ratio,
            "duration": minutes_between(signal_time, close_date),
            "would_v2_have_allowed": dec["allow"],
            "would_v2_have_blocked": not dec["allow"],
            "v2_outcome_label": label,
        })
    if not trades:
        latest = load_json(MARKET_LATEST, {})
        journal_rows.append({
            "journal_time": now(),
            "rule_version": rule_version,
            "config_hash": config_hash,
            "bot_running": bot_running,
            "dry_run": dry_run,
            "pair": "",
            "signal_time": "",
            "enter_tag": "",
            "market_sentiment_score": latest.get("market_sentiment_score", ""),
            "primary_regime": latest.get("primary_regime", ""),
            "regime_tags": latest.get("regime_tags", ""),
            "pair_quality_score": "",
            "risk_score": "",
            "opportunity_score": "",
            "final_score": "",
            "v2_decision": "",
            "stake_multiplier": "",
            "v2_reason": "",
            "actual_dry_run_action": "none_observed",
            "actual_trade_id": "",
            "consistency_status": "no_new_signal",
            "observation_status": "heartbeat",
            "notes": "No dry-run trades found in local DB; signal detection limited to API/log/DB fallback.",
        })
    return journal_rows, outcome_rows


def write_consistency() -> None:
    rows = read_csv(JOURNAL)
    counts: dict[str, int] = {}
    for row in rows:
        status = row.get("consistency_status") or "unknown"
        counts[status] = counts.get(status, 0) + 1
    out = [{"consistency_status": key, "count": value} for key, value in sorted(counts.items())]
    write_csv(CONSISTENCY, out, ["consistency_status", "count"])


def main() -> int:
    REPORT_OUT.mkdir(parents=True, exist_ok=True)
    USER_OUT.mkdir(parents=True, exist_ok=True)
    log: list[str] = [f"generated_at={now()}", f"project={PROJECT_ROOT}"]
    before = RUNTIME_CONFIG.read_bytes() if RUNTIME_CONFIG.exists() else b""
    safe = safety_check()
    if not safe["pass"]:
        raise RuntimeError(f"Unsafe runtime config: {safe['checks']}")
    meta = freeze_v2_rules(log)
    api_status = read_api_status(safe["config"])
    journal_rows, outcome_rows = build_rows(meta, safe, api_status, log)
    append_csv(JOURNAL, journal_rows, JOURNAL_FIELDS)
    write_csv(OUTCOMES, outcome_rows, OUTCOME_FIELDS)
    write_consistency()
    after = RUNTIME_CONFIG.read_bytes() if RUNTIME_CONFIG.exists() else b""
    log.append(f"runtime_config_untouched={before == after}")
    log.append(f"journal_rows_appended={len(journal_rows)}")
    log.append(f"outcome_rows_written={len(outcome_rows)}")
    log.append(f"journal={JOURNAL}")
    log.append(f"outcomes={OUTCOMES}")
    LOGS.write_text("\n".join(log) + "\n", encoding="utf-8")
    for line in log:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
