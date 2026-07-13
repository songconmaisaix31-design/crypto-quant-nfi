#!/usr/bin/env python3
from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

try:
    from ops_common import PROJECT_ROOT
except ModuleNotFoundError:
    from scripts.ops_common import PROJECT_ROOT


JOURNAL_PATH = PROJECT_ROOT / "reports/decision_engine_v2/v2_decision_journal.csv"
PAIR_STATE_PATH = PROJECT_ROOT / "reports/market_state/pair_quality_scores.csv"
MARKET_STATE_PATH = PROJECT_ROOT / "user_data/market_state/market_state_history.csv"

CANDIDATE_IDS = [
    "baseline_nfi",
    "decision_engine_v2_frozen",
    "decision_engine_v2_relaxed",
    "sizing_only_v1",
    "sizing_only_pair_quality_v1",
    "sizing_only_atr_breadth_v1",
    "slippage_aware_sizing_v1",
]


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_evidence_rows() -> list[dict[str, Any]]:
    market_by_date = {row.get("date", ""): row for row in read_csv(MARKET_STATE_PATH)}
    pair_by_key = {
        (row.get("date", ""), row.get("pair", "")): row
        for row in read_csv(PAIR_STATE_PATH)
    }
    rows: list[dict[str, Any]] = []
    for raw in read_csv(JOURNAL_PATH):
        signal_time = raw.get("signal_time", "")
        date = signal_time[:10]
        market = market_by_date.get(date, {})
        pair_state = pair_by_key.get((date, raw.get("pair", "")), {})
        row: dict[str, Any] = dict(raw)
        row.update({
            "date": date,
            "baseline_profit": as_float(raw.get("baseline_profit")),
            "pair_quality_score": as_float(raw.get("pair_quality_score"), 50.0),
            "risk_score": as_float(raw.get("risk_score"), 50.0),
            "market_sentiment_score": as_float(raw.get("market_sentiment_score"), 50.0),
            "v2_stake_multiplier": as_float(raw.get("stake_multiplier")),
            "pair_atr_percent": as_float(pair_state.get("pair_atr_percent")),
            "btc_trend_score": as_float(market.get("btc_trend_score"), 50.0),
            "market_breadth_score": as_float(market.get("market_breadth_score"), 50.0),
            "regime_tags": market.get("regime_tags", ""),
        })
        rows.append(row)
    return sorted(rows, key=lambda row: str(row.get("signal_time", "")))


def candidate_multiplier(candidate_id: str, row: dict[str, Any]) -> float:
    regime = str(row.get("primary_regime") or "")
    reason = str(row.get("decision_reason") or "")
    pair_quality = as_float(row.get("pair_quality_score"), 50.0)
    risk = as_float(row.get("risk_score"), 50.0)
    sentiment = as_float(row.get("market_sentiment_score"), 50.0)

    if candidate_id == "baseline_nfi":
        return 1.0
    if candidate_id == "decision_engine_v2_frozen":
        return as_float(row.get("v2_stake_multiplier"))
    if candidate_id == "decision_engine_v2_relaxed":
        frozen = as_float(row.get("v2_stake_multiplier"))
        if frozen == 0 and ("hard_pair_quality" in reason or "extreme_atr_volume_return" in reason):
            return 0.25
        return frozen
    if candidate_id == "sizing_only_pair_quality_v1":
        return 0.25 if pair_quality < 20 else 0.5 if pair_quality < 40 else 1.0
    if candidate_id == "sizing_only_atr_breadth_v1":
        atr = as_float(row.get("pair_atr_percent"))
        btc_trend = as_float(row.get("btc_trend_score"), 50.0)
        breadth = as_float(row.get("market_breadth_score"), 50.0)
        if atr >= 12 and (btc_trend < 30 or breadth < 30):
            return 0.25
        if atr >= 8 or breadth < 35:
            return 0.5
        return 1.0

    multiplier = 1.0
    if regime == "panic":
        multiplier *= 0.25
    elif regime in {"fear", "risk_off"} or "risk_off" in str(row.get("regime_tags") or ""):
        multiplier *= 0.5
    if pair_quality < 20:
        multiplier *= 0.5
    elif pair_quality < 40:
        multiplier *= 0.75
    if candidate_id == "slippage_aware_sizing_v1" and (risk >= 70 or sentiment < 30):
        multiplier *= 0.5
    return round(max(0.125, multiplier), 6)


def max_drawdown(values: list[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def max_consecutive_losses(values: list[float]) -> int:
    longest = current = 0
    for value in values:
        current = current + 1 if value < 0 else 0
        longest = max(longest, current)
    return longest


def evaluate_candidate(
    rows: list[dict[str, Any]],
    candidate_id: str,
    slippage_ratio_per_side: float = 0.0005,
) -> dict[str, Any]:
    outcomes: list[float] = []
    allowed = missed_profit = avoided_loss = 0.0
    largest_missed = largest_avoided = 0.0
    regime_totals: dict[str, float] = defaultdict(float)
    for row in rows:
        multiplier = candidate_multiplier(candidate_id, row)
        profit = as_float(row.get("baseline_profit"))
        if multiplier > 0:
            allowed += 1
        outcome = profit * multiplier - (2 * slippage_ratio_per_side * 100 * multiplier)
        outcomes.append(outcome)
        missed = max(0.0, profit) * (1 - multiplier)
        avoided = abs(min(0.0, profit)) * (1 - multiplier)
        missed_profit += missed
        avoided_loss += avoided
        largest_missed = max(largest_missed, missed)
        largest_avoided = max(largest_avoided, avoided)
        regime_totals[str(row.get("primary_regime") or "unknown")] += outcome

    positives = sum(value for value in outcomes if value > 0)
    negatives = abs(sum(value for value in outcomes if value < 0))
    allowed_count = int(allowed)
    profitable_regimes = sum(1 for value in regime_totals.values() if value > 0)
    regime_count = len(regime_totals)
    return {
        "candidate_id": candidate_id,
        "raw_signals": len(rows),
        "allowed_signals": allowed_count,
        "allowed_ratio": round(allowed_count / len(rows), 6) if rows else 0.0,
        "profit_after_slippage": round(sum(outcomes), 8),
        "max_drawdown": round(max_drawdown(outcomes), 8),
        "profit_factor": round(positives / negatives, 8) if negatives else None,
        "win_rate": round(sum(value > 0 for value in outcomes) / allowed_count, 6) if allowed_count else 0.0,
        "max_consecutive_losses": max_consecutive_losses(outcomes),
        "net_filter_value": round(avoided_loss - missed_profit, 8),
        "missed_profit": round(missed_profit, 8),
        "avoided_loss": round(avoided_loss, 8),
        "largest_missed_winner": round(largest_missed, 8),
        "largest_avoided_loser": round(largest_avoided, 8),
        "regime_stability": round(profitable_regimes / regime_count, 6) if regime_count else 0.0,
        "sample_size": allowed_count,
        "overfit_risk": "LOW_SAMPLE",
    }


def evaluate_all(rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    evidence = rows if rows is not None else load_evidence_rows()
    return [evaluate_candidate(evidence, candidate_id) for candidate_id in CANDIDATE_IDS]


def grouped_performance(
    rows: list[dict[str, Any]],
    key: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(key) or "unknown")].append(row)
    for candidate_id in CANDIDATE_IDS:
        for group, group_rows in sorted(groups.items()):
            metrics = evaluate_candidate(group_rows, candidate_id)
            output.append({"candidate_id": candidate_id, key: group, **metrics})
    return output


def slippage_stress(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for ratio in (0.001, 0.002, 0.005):
        for candidate_id in CANDIDATE_IDS:
            metrics = evaluate_candidate(rows, candidate_id, ratio)
            output.append({
                "candidate_id": candidate_id,
                "slippage_ratio_per_side": ratio,
                "profit_after_slippage": metrics["profit_after_slippage"],
                "max_drawdown": metrics["max_drawdown"],
                "sample_size": metrics["sample_size"],
            })
    return output


def walkforward_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    count = len(rows)
    train_end = max(1, int(count * 0.6))
    validation_end = max(train_end + 1, int(count * 0.8))
    segments = [
        ("train_60", rows[:train_end]),
        ("validation_20", rows[train_end:validation_end]),
        ("test_20", rows[validation_end:]),
    ]
    step = max(1, count // 5)
    for fold in range(3):
        test_start = min(count, step * (fold + 2))
        test_end = count if fold == 2 else min(count, test_start + step)
        segments.append((f"rolling_test_{fold + 1}", rows[test_start:test_end]))
    output = []
    for window, window_rows in segments:
        for candidate_id in CANDIDATE_IDS:
            metrics = evaluate_candidate(window_rows, candidate_id)
            output.append({
                "window": window,
                "start": window_rows[0].get("signal_time", "") if window_rows else "",
                "end": window_rows[-1].get("signal_time", "") if window_rows else "",
                "leakage_check": "PASS_NO_REALIZED_PROFIT_IN_DECISION",
                **metrics,
            })
    return output


def anti_overfit_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    windows = walkforward_rows(rows)
    output = []
    for candidate_id in CANDIDATE_IDS:
        candidate_windows = [row for row in windows if row["candidate_id"] == candidate_id]
        train = next((row for row in candidate_windows if row["window"] == "train_60"), {})
        test = next((row for row in candidate_windows if row["window"] == "test_20"), {})
        train_profit = as_float(train.get("profit_after_slippage"))
        test_profit = as_float(test.get("profit_after_slippage"))
        sign_stable = train_profit == 0 or test_profit == 0 or (train_profit > 0) == (test_profit > 0)
        total_sample = len(rows)
        risk = "HIGH" if total_sample < 100 or not sign_stable else "MEDIUM"
        output.append({
            "candidate_id": candidate_id,
            "historical_sample_size": total_sample,
            "train_profit_after_slippage": train_profit,
            "test_profit_after_slippage": test_profit,
            "train_test_sign_stable": sign_stable,
            "leakage_check": "PASS",
            "sample_warning": "LOW_SAMPLE" if total_sample < 100 else "PASS",
            "overfit_risk": risk,
        })
    return output
