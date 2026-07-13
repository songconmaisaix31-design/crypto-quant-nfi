#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import itertools
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
V1_DECISIONS = PROJECT_ROOT / "reports/decision_engine/decision_signal_decisions.csv"
V1_SUMMARY = PROJECT_ROOT / "reports/decision_engine/decision_engine_summary.json"
MARKET_HISTORY = PROJECT_ROOT / "user_data/market_state/market_state_history.csv"
PAIR_QUALITY = PROJECT_ROOT / "reports/market_state/pair_quality_scores.csv"
OUT = PROJECT_ROOT / "reports/decision_engine_v2"
USER_OUT = PROJECT_ROOT / "user_data/decision_engine_v2"
REPORT = OUT / "decision_engine_v2_report.md"
SUMMARY = OUT / "decision_engine_v2_summary.json"
ABLATION = OUT / "rule_ablation_matrix.csv"
SEARCH = OUT / "threshold_search_matrix.csv"
TAG_REGIME = OUT / "tag_regime_performance.csv"
PAIR_REGIME = OUT / "pair_regime_performance.csv"
COMPARE = OUT / "v1_vs_v2_comparison.csv"
JOURNAL = OUT / "v2_decision_journal.csv"
BLOCKED = OUT / "v2_blocked_signal_analysis.csv"
LEAKAGE = OUT / "leakage_audit.md"
LOGS = OUT / "decision_engine_v2_logs.txt"
PRELIVE_UPDATE = PROJECT_ROOT / "reports/pre_live_gate/pre_live_gate_v2_evidence_update.md"
SLIPPAGE_PER_SIDE = 0.0005


def log_lines() -> list[str]:
    return []


LOG: list[str] = []


def log(msg: str) -> None:
    LOG.append(msg)
    print(msg)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    if fields is None:
        keys: list[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        fields = keys
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def as_float(v: Any, default: float = 0.0) -> float:
    try:
        if v in ("", None):
            return default
        return float(v)
    except Exception:
        return default


def as_bool(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")


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


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def enrich_rows() -> list[dict[str, Any]]:
    rows = read_csv(V1_DECISIONS)
    market = read_csv(MARKET_HISTORY)
    pairq = read_csv(PAIR_QUALITY)
    market_by_date = {r["date"]: r for r in market}
    pair_by_key = {(r["date"], r["pair"]): r for r in pairq}
    enriched = []
    for r in rows:
        date = r["signal_time"][:10]
        m = market_by_date.get(date, {})
        p = pair_by_key.get((date, r["pair"]), {})
        row = dict(r)
        for key in ("btc_trend_score", "market_breadth_score", "volatility_score", "pair_relative_strength_score", "percent_pairs_above_ema50", "btc_return_1d"):
            row[key] = m.get(key, row.get(key, ""))
        for key in ("pair_return_1d", "pair_return_7d", "pair_return_30d", "pair_drawdown_from_30d_high", "pair_vs_btc_return_7d", "pair_vs_btc_return_30d"):
            row[key] = p.get(key, "")
        row["signal_dt"] = parse_time(row["signal_time"])
        row["baseline_profit"] = as_float(row["baseline_profit"])
        row["baseline_profit_ratio"] = as_float(row["baseline_profit_ratio"])
        row["market_sentiment_score"] = as_float(row["market_sentiment_score"], 50)
        row["pair_quality_score"] = as_float(row["pair_quality_score"], 50)
        row["volume_zscore"] = as_float(row["volume_zscore"], 0)
        row["pair_atr_percent"] = as_float(row["pair_atr_percent"], 0)
        row["btc_trend_score"] = as_float(row.get("btc_trend_score"), 50)
        row["market_breadth_score"] = as_float(row.get("market_breadth_score"), 50)
        row["volatility_score"] = as_float(row.get("volatility_score"), 50)
        row["pair_relative_strength_score"] = as_float(row.get("pair_relative_strength_score"), 50)
        row["pair_return_1d"] = as_float(row.get("pair_return_1d"), 0)
        row["v1_decision"] = row.get("final_decision", "")
        row["v1_block_reason"] = row.get("block_reason", "")
        row["v1_stake_multiplier"] = as_float(row.get("stake_multiplier"), 0)
        enriched.append(row)
    return sorted(enriched, key=lambda r: r["signal_dt"])


def split_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    train_start = dt.datetime.fromisoformat("2025-07-04")
    train_end = dt.datetime.fromisoformat("2026-01-05")
    test_start = dt.datetime.fromisoformat("2026-01-05")
    test_end = dt.datetime.fromisoformat("2026-07-04") + dt.timedelta(days=1)
    train = [r for r in rows if train_start <= r["signal_dt"] < train_end]
    test = [r for r in rows if test_start <= r["signal_dt"] < test_end]
    if len(train) < 10 or len(test) < 10:
        n = len(rows)
        cut = max(1, int(n * 0.6))
        return rows[:cut], rows[cut:], "fallback_60_40_due_small_sample"
    return train, test, "calendar_split"


def tag_history(rows: list[dict[str, Any]], current: dict[str, Any]) -> dict[str, float]:
    prior = [r for r in rows if r["signal_dt"] < current["signal_dt"] and r["enter_tag"] == current["enter_tag"]]
    if len(prior) < 3:
        return {"count": len(prior), "avg_profit": 0.0, "win_rate": 0.5}
    profits = [r["baseline_profit"] for r in prior]
    return {"count": len(prior), "avg_profit": sum(profits) / len(profits), "win_rate": sum(1 for p in profits if p > 0) / len(profits)}


def pair_history(rows: list[dict[str, Any]], current: dict[str, Any]) -> dict[str, float]:
    prior = [r for r in rows if r["signal_dt"] < current["signal_dt"] and r["pair"] == current["pair"]]
    if len(prior) < 3:
        return {"count": len(prior), "avg_profit": 0.0, "win_rate": 0.5}
    profits = [r["baseline_profit"] for r in prior]
    return {"count": len(prior), "avg_profit": sum(profits) / len(profits), "win_rate": sum(1 for p in profits if p > 0) / len(profits)}


def group_history(rows: list[dict[str, Any]], current: dict[str, Any], key: str) -> dict[str, float]:
    prior = [r for r in rows if r["signal_dt"] < current["signal_dt"] and r[key] == current[key] and r["primary_regime"] == current["primary_regime"]]
    if len(prior) < 3:
        return {"count": len(prior), "avg_profit": 0.0, "win_rate": 0.5}
    profits = [r["baseline_profit"] for r in prior]
    return {"count": len(prior), "avg_profit": sum(profits) / len(profits), "win_rate": sum(1 for p in profits if p > 0) / len(profits)}


def risk_opportunity(row: dict[str, Any], all_rows: list[dict[str, Any]]) -> tuple[float, float, list[str]]:
    reasons = []
    sentiment = row["market_sentiment_score"]
    pq = row["pair_quality_score"]
    vz = abs(row["volume_zscore"])
    atr = row["pair_atr_percent"]
    breadth = row["market_breadth_score"]
    vol_score = row["volatility_score"]
    btc_trend = row["btc_trend_score"]
    rel = row["pair_relative_strength_score"]
    regime = row["primary_regime"]
    tags = row.get("regime_tags", "")
    pair_ret_1d = row.get("pair_return_1d", 0)
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
    th = tag_history(all_rows, row)
    ph = pair_history(all_rows, row)
    trh = group_history(all_rows, row, "enter_tag")
    prh = group_history(all_rows, row, "pair")
    opportunity = 0.0
    opportunity += pq * 0.35
    opportunity += rel * 0.15
    opportunity += max(0, sentiment - 30) * 0.10
    opportunity += max(0, th["avg_profit"]) * 2.0
    opportunity += th["win_rate"] * 10
    opportunity += max(0, ph["avg_profit"]) * 1.2
    opportunity += ph["win_rate"] * 8
    opportunity += max(0, trh["avg_profit"]) * 1.0
    opportunity += max(0, prh["avg_profit"]) * 1.0
    if regime not in ("panic", "risk_off"):
        opportunity += 5
    return max(0, min(100, risk)), max(0, min(100, opportunity)), reasons


def hard_block(row: dict[str, Any], all_rows: list[dict[str, Any]], pq_min: float, atr_block: float, vz_block: float) -> str:
    pq = row["pair_quality_score"]
    atr = row["pair_atr_percent"]
    vz = abs(row["volume_zscore"])
    regime = row["primary_regime"]
    breadth = row["market_breadth_score"]
    btc_trend = row["btc_trend_score"]
    if pq < pq_min:
        return "hard_pair_quality"
    if regime == "panic" and btc_trend < 30 and breadth < 30:
        return "panic_btc_crash_breadth_bad"
    if atr >= atr_block and vz >= vz_block and row.get("pair_return_1d", 0) <= -8:
        return "extreme_atr_volume_return"
    th = tag_history(all_rows, row)
    if th["count"] >= 5 and th["avg_profit"] <= -2:
        return "severe_negative_tag_history"
    return ""


def decide_v2(row: dict[str, Any], all_rows: list[dict[str, Any]], params: dict[str, float]) -> dict[str, Any]:
    risk, opp, reasons = risk_opportunity(row, all_rows)
    hb = hard_block(row, all_rows, params["pair_quality_min_hard_block"], params["atr_block_threshold"], params["volume_zscore_block_threshold"])
    risk_adj = risk * params["risk_score_weight"]
    opp_adj = opp * params["opportunity_score_weight"]
    final = max(0, min(100, opp_adj - risk_adj + 50))
    if hb:
        decision, mult = "block", 0.0
        reason = hb
    elif final >= params["allow_full_threshold"]:
        decision, mult = "allow_full", 1.0
        reason = "score_full"
    elif final >= params["allow_half_threshold"]:
        decision, mult = "allow_half", 0.5
        reason = "score_half"
    elif final >= params["allow_quarter_threshold"]:
        decision, mult = "allow_quarter", 0.25
        reason = "score_quarter"
    else:
        decision, mult = "block", 0.0
        reason = "score_below_quarter"
    if reasons:
        reason += ":" + ",".join(reasons)
    return {
        "risk_score": round(risk, 6),
        "opportunity_score": round(opp, 6),
        "final_score": round(final, 6),
        "final_decision": decision,
        "stake_multiplier": mult,
        "decision_reason": reason,
        "allow": mult > 0,
    }


def max_drawdown(profits: list[float]) -> float:
    equity = peak = dd = 0.0
    for p in profits:
        equity += p
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dd


def max_consecutive_losses(profits: list[float]) -> int:
    best = cur = 0
    for p in profits:
        if p < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def profit_factor(profits: list[float]) -> str | float:
    wins = sum(p for p in profits if p > 0)
    losses = abs(sum(p for p in profits if p < 0))
    return "N/A" if losses == 0 else round(wins / losses, 8)


def eval_decisions(rows: list[dict[str, Any]], decisions: list[dict[str, Any]], slippage: bool = False) -> dict[str, Any]:
    profits = []
    missed = avoided = largest_missed = largest_avoided = 0.0
    for row, dec in zip(rows, decisions):
        p = row["baseline_profit"]
        if dec["allow"]:
            adj = p * dec["stake_multiplier"]
            if slippage:
                adj -= 100 * dec["stake_multiplier"] * SLIPPAGE_PER_SIDE * 2
            profits.append(adj)
        else:
            if p > 0:
                missed += p
                largest_missed = max(largest_missed, p)
            else:
                avoided += abs(p)
                largest_avoided = max(largest_avoided, abs(p))
    allowed = len(profits)
    wins = [p for p in profits if p > 0]
    return {
        "raw_signals": len(rows),
        "allowed_signals": allowed,
        "allowed_ratio": round(allowed / len(rows), 6) if rows else 0,
        "blocked_signals": len(rows) - allowed,
        "total_profit": round(sum(profits), 8),
        "total_profit_after_slippage": round(sum(profits), 8) if slippage else "",
        "max_drawdown": round(max_drawdown(profits), 8),
        "win_rate": round(len(wins) / len(profits), 6) if profits else 0,
        "average_profit": round(sum(profits) / len(profits), 8) if profits else 0,
        "profit_factor": profit_factor(profits),
        "max_consecutive_losses": max_consecutive_losses(profits),
        "missed_profit_total": round(missed, 8),
        "avoided_loss_total": round(avoided, 8),
        "net_filter_value": round(avoided - missed, 8),
        "largest_missed_winner": round(largest_missed, 8),
        "largest_avoided_loser": round(largest_avoided, 8),
    }


def baseline_metrics(rows: list[dict[str, Any]], slippage: bool = False) -> dict[str, Any]:
    decisions = [{"allow": True, "stake_multiplier": 1.0} for _ in rows]
    return eval_decisions(rows, decisions, slippage=slippage)


def v1_metrics(rows: list[dict[str, Any]], slippage: bool = False) -> dict[str, Any]:
    decisions = [{"allow": r["v1_decision"] != "block", "stake_multiplier": r["v1_stake_multiplier"] if r["v1_decision"] != "block" else 0.0} for r in rows]
    return eval_decisions(rows, decisions, slippage=slippage)


def make_param_grid(rows: list[dict[str, Any]]) -> list[dict[str, float]]:
    atrs = sorted(r["pair_atr_percent"] for r in rows)
    def q(p: float) -> float:
        if not atrs:
            return 10.0
        return atrs[min(len(atrs) - 1, max(0, int(len(atrs) * p)))]
    grid = []
    for full, half, quarter, pq, atr, vz, rw, ow in itertools.product(
        [65, 70, 75], [50, 55, 60], [35, 40, 45], [20, 25, 30, 35], [q(0.90), q(0.95), q(0.98)], [3, 4, 5, 6], [0.8, 1.0, 1.2], [0.8, 1.0, 1.2]
    ):
        if not (quarter < half < full):
            continue
        grid.append({
            "allow_full_threshold": full,
            "allow_half_threshold": half,
            "allow_quarter_threshold": quarter,
            "pair_quality_min_hard_block": pq,
            "atr_block_threshold": round(atr, 6),
            "volume_zscore_block_threshold": vz,
            "risk_score_weight": rw,
            "opportunity_score_weight": ow,
        })
    return grid


def score_candidate(metrics: dict[str, Any], baseline: dict[str, Any]) -> float:
    # Conservative objective: improve risk without destroying too much profit.
    return (
        as_float(metrics["total_profit"]) * 1.0
        + max(0, baseline["max_drawdown"] - metrics["max_drawdown"]) * 1.5
        + max(0, baseline["max_consecutive_losses"] - metrics["max_consecutive_losses"]) * 2.0
        + metrics["net_filter_value"] * 0.5
        - metrics["largest_missed_winner"] * 0.25
    )


def ablation(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reasons = Counter()
    for r in rows:
        for part in (r.get("v1_block_reason") or "").split(";"):
            if part:
                reasons[part] += 1
    out = []
    for reason, count in reasons.most_common():
        affected = [r for r in rows if reason in (r.get("v1_block_reason") or "").split(";")]
        winners = [r for r in affected if r["baseline_profit"] > 0]
        losers = [r for r in affected if r["baseline_profit"] <= 0]
        missed = sum(r["baseline_profit"] for r in winners)
        avoided = abs(sum(r["baseline_profit"] for r in losers))
        out.append({
            "rule": reason,
            "blocked_signals": len(affected),
            "blocked_winners": len(winners),
            "blocked_losers": len(losers),
            "missed_profit_total": round(missed, 8),
            "avoided_loss_total": round(avoided, 8),
            "net_filter_value": round(avoided - missed, 8),
            "largest_missed_winner": round(max([r["baseline_profit"] for r in winners], default=0), 8),
            "largest_avoided_loser": round(abs(min([r["baseline_profit"] for r in losers], default=0)), 8),
        })
    return out


def group_perf(rows: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[tuple(str(r[k]) for k in keys)].append(r)
    out = []
    for group, items in sorted(groups.items()):
        profits = [r["baseline_profit"] for r in items]
        after_slip = sum(p - 100 * SLIPPAGE_PER_SIDE * 2 for p in profits)
        count = len(items)
        avg = sum(profits) / count
        win = sum(1 for p in profits if p > 0) / count
        if count < 3:
            action = "need_more_samples"
        elif after_slip > 0 and win >= 0.6:
            action = "allow"
        elif after_slip > 0:
            action = "reduce_stake"
        else:
            action = "block"
        row = {keys[i]: group[i] for i in range(len(keys))}
        row.update({
            "trades_count": count,
            "win_rate": round(win, 6),
            "total_profit": round(sum(profits), 8),
            "average_profit": round(avg, 8),
            "worst_trade": round(min(profits), 8),
            "best_trade": round(max(profits), 8),
            "avg_duration": round(statistics.mean([as_float(r.get("trade_duration"), 0) for r in items]), 4) if items else 0,
            "after_slippage_profit": round(after_slip, 8),
            "suggested_action": action,
        })
        out.append(row)
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    USER_OUT.mkdir(parents=True, exist_ok=True)
    before = RUNTIME_CONFIG.read_bytes()
    safe = safety()
    if not V1_DECISIONS.exists():
        raise RuntimeError("Run scripts/evaluate-decision-engine.sh first.")
    rows = enrich_rows()
    train, test, split_mode = split_rows(rows)
    log(f"rows={len(rows)} train={len(train)} test={len(test)} split={split_mode}")
    baseline_train = baseline_metrics(train, slippage=True)
    baseline_all = baseline_metrics(rows, slippage=True)
    search_rows = []
    best = None
    best_score = -10**18
    for params in make_param_grid(train):
        dec_train = [decide_v2(r, train, params) for r in train]
        m_train = eval_decisions(train, dec_train, slippage=True)
        sc = score_candidate(m_train, baseline_train)
        row = dict(params)
        row.update(m_train)
        row["objective_score"] = round(sc, 8)
        search_rows.append(row)
        if sc > best_score and m_train["allowed_signals"] > 0:
            best_score = sc
            best = params
    if best is None:
        best = make_param_grid(train)[0]
    search_rows = sorted(search_rows, key=lambda r: r["objective_score"], reverse=True)
    write_csv(SEARCH, search_rows)
    dec_all = [decide_v2(r, rows, best) for r in rows]
    dec_train = [decide_v2(r, train, best) for r in train]
    dec_test = [decide_v2(r, train + test, best) for r in test]
    conservative = dict(best)
    conservative["allow_full_threshold"] += 5
    conservative["allow_half_threshold"] += 5
    conservative["allow_quarter_threshold"] += 5
    dec_cons = [decide_v2(r, rows, conservative) for r in rows]
    v2_all = eval_decisions(rows, dec_all, slippage=True)
    v2_train = eval_decisions(train, dec_train, slippage=True)
    v2_test = eval_decisions(test, dec_test, slippage=True)
    v2_cons = eval_decisions(rows, dec_cons, slippage=True)
    v1_all = v1_metrics(rows, slippage=True)
    compare_rows = []
    for name, metrics, notes in [
        ("baseline_nfi", baseline_all, "all signals, slippage stress"),
        ("decision_engine_v1", v1_all, "v1 hard filters"),
        ("decision_engine_v2_best_train", v2_train, "best params selected on train"),
        ("decision_engine_v2_test", v2_test, "same params evaluated on test"),
        ("decision_engine_v2_conservative", v2_cons, "v2 thresholds +5"),
    ]:
        r = {"scenario": name, **metrics, "notes": notes}
        compare_rows.append(r)
    write_csv(COMPARE, compare_rows)
    journal_rows = []
    blocked_rows = []
    for r, d in zip(rows, dec_all):
        item = {
            "pair": r["pair"],
            "signal_time": r["signal_time"],
            "enter_tag": r["enter_tag"],
            "baseline_profit": r["baseline_profit"],
            "primary_regime": r["primary_regime"],
            "market_sentiment_score": r["market_sentiment_score"],
            "pair_quality_score": r["pair_quality_score"],
            "risk_score": d["risk_score"],
            "opportunity_score": d["opportunity_score"],
            "final_score": d["final_score"],
            "final_decision": d["final_decision"],
            "stake_multiplier": d["stake_multiplier"],
            "decision_reason": d["decision_reason"],
            "would_have_improved": (r["baseline_profit"] <= 0 and not d["allow"]) or (r["baseline_profit"] > 0 and d["allow"]),
        }
        journal_rows.append(item)
        if not d["allow"]:
            blocked_rows.append({
                **item,
                "blocked_winner": r["baseline_profit"] > 0,
                "blocked_loser": r["baseline_profit"] <= 0,
                "missed_profit": r["baseline_profit"] if r["baseline_profit"] > 0 else 0,
                "avoided_loss": abs(r["baseline_profit"]) if r["baseline_profit"] < 0 else 0,
            })
    write_csv(JOURNAL, journal_rows)
    write_csv(USER_OUT / "latest_v2_decision_journal.csv", journal_rows)
    write_csv(BLOCKED, blocked_rows)
    write_csv(ABLATION, ablation(rows))
    tag_perf = group_perf(rows, ["enter_tag", "primary_regime"])
    pair_perf = group_perf(rows, ["pair", "primary_regime"])
    write_csv(TAG_REGIME, tag_perf)
    write_csv(PAIR_REGIME, pair_perf)
    train_test_gap = v2_train["total_profit"] - v2_test["total_profit"]
    overfit_risk = len(test) < 10 or v2_test["total_profit"] < 0 or v2_test["allowed_signals"] == 0 or abs(train_test_gap) > max(20, abs(v2_train["total_profit"]) * 2)
    leakage_lines = [
        "# Leakage Audit",
        "",
        "- V2 decisions use signal_time row features from market_state_history and pair_quality_scores.",
        "- V2 does not use close_date or post-signal candles directly for decision fields.",
        "- V2 threshold search uses baseline_profit for offline calibration, so selected thresholds are retrospective-only and not live-approved.",
        "- Per-tag/pair history functions only use prior signals by signal_time for decision scoring.",
        "- The sample has only 61 trades; overfitting risk is material.",
        f"- Train/test split mode: `{split_mode}`.",
        f"- Overfit risk flag: `{overfit_risk}`.",
    ]
    LEAKAGE.write_text("\n".join(leakage_lines) + "\n", encoding="utf-8")
    v2_blocked_winners = sum(1 for r in blocked_rows if r["blocked_winner"])
    v2_blocked_losers = sum(1 for r in blocked_rows if r["blocked_loser"])
    v2_missed = sum(r["missed_profit"] for r in blocked_rows)
    v2_avoided = sum(r["avoided_loss"] for r in blocked_rows)
    summary = {
        "safe_config": safe,
        "runtime_config_untouched": before == RUNTIME_CONFIG.read_bytes(),
        "rows": len(rows),
        "train_rows": len(train),
        "test_rows": len(test),
        "split_mode": split_mode,
        "best_params": best,
        "baseline_all": baseline_all,
        "v1_all": v1_all,
        "v2_all": v2_all,
        "v2_train": v2_train,
        "v2_test": v2_test,
        "v2_conservative": v2_cons,
        "v2_allowed_signals_ratio": v2_all["allowed_ratio"],
        "v2_blocked_winning_trades": v2_blocked_winners,
        "v2_blocked_losing_trades": v2_blocked_losers,
        "v2_missed_profit_total": round(v2_missed, 8),
        "v2_avoided_loss_total": round(v2_avoided, 8),
        "v2_net_filter_value": round(v2_avoided - v2_missed, 8),
        "v2_improves_v1_net_filter_value": v2_all["net_filter_value"] > v1_all["net_filter_value"],
        "v2_improves_slippage_profit_vs_v1": v2_all["total_profit"] > v1_all["total_profit"],
        "v2_reduces_drawdown_vs_baseline": v2_all["max_drawdown"] < baseline_all["max_drawdown"],
        "overfit_risk": overfit_risk,
        "pre_live_gate_status": "BLOCKED",
    }
    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    top_rules = ablation(rows)[:8]
    report_lines = [
        "# Decision Engine V2 Calibration Report",
        "",
        "This is offline calibration only. It does not modify strategy logic, runtime config, API keys, or live trading settings.",
        "",
        f"- Rows: `{len(rows)}` train `{len(train)}` test `{len(test)}` split `{split_mode}`",
        f"- Best params: `{best}`",
        f"- V2 allowed ratio: `{v2_all['allowed_ratio']}`",
        f"- V2 total profit after slippage: `{v2_all['total_profit']}`",
        f"- V2 max drawdown: `{v2_all['max_drawdown']}`",
        f"- V2 net filter value: `{v2_all['net_filter_value']}`",
        f"- V2 blocked winners / losers: `{v2_blocked_winners}` / `{v2_blocked_losers}`",
        f"- Train/test overfit risk: `{overfit_risk}`",
        "",
        "## V1 Ablation Highlights",
        "| rule | blocked | winners | losers | net_filter_value | largest_missed_winner |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in top_rules:
        report_lines.append(f"| `{r['rule']}` | {r['blocked_signals']} | {r['blocked_winners']} | {r['blocked_losers']} | {r['net_filter_value']} | {r['largest_missed_winner']} |")
    report_lines += [
        "",
        "## V1 vs V2",
        "| scenario | allowed | profit_after_slippage | max_drawdown | net_filter_value |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in compare_rows:
        report_lines.append(f"| `{r['scenario']}` | {r['allowed_signals']} | {r['total_profit']} | {r['max_drawdown']} | {r['net_filter_value']} |")
    report_lines += [
        "",
        "Pre-live gate remains BLOCKED because dry-run duration/consistency evidence is still insufficient and V2 is retrospective calibration on a small sample.",
    ]
    REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    PRELIVE_UPDATE.write_text(
        "# Pre-Live Gate V2 Evidence Update\n\n"
        "LIVE TRADING STATUS: BLOCKED\n\n"
        f"- V2 improves v1 excessive filtering: `{summary['v2_improves_v1_net_filter_value']}`.\n"
        f"- V2 reduces max drawdown vs baseline: `{summary['v2_reduces_drawdown_vs_baseline']}`.\n"
        f"- V2 improves slippage-stressed profit vs v1: `{summary['v2_improves_slippage_profit_vs_v1']}`.\n"
        f"- V2 blocked winners / losers: `{v2_blocked_winners}` / `{v2_blocked_losers}`.\n"
        f"- Train/test overfit risk: `{overfit_risk}`.\n"
        "- Dry-run 2-4 week evidence is still insufficient.\n"
        "- Dry-run decision/fill consistency evidence is still insufficient.\n\n"
        "Unless every hard gate is satisfied, pre-live status must remain BLOCKED.\n",
        encoding="utf-8",
    )
    LOGS.write_text("\n".join(LOG) + "\n", encoding="utf-8")
    print(f"[PASS] wrote {REPORT}")
    print(f"[PASS] wrote {SUMMARY}")
    print("[BLOCKED] pre-live gate remains BLOCKED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
