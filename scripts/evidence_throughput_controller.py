#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

from dry_run_status import dry_run_status
from ops_common import PROJECT_ROOT, git_info, load_json, phase_record, utc_now, write_json


OUT = PROJECT_ROOT / "reports/evidence_throughput"
SUMMARY = OUT / "evidence_throughput_summary.json"
REPORT = OUT / "evidence_throughput_report.md"
HISTORY = OUT / "evidence_throughput_history.csv"
CONTEXT = PROJECT_ROOT / "reports/CONTEXT.md"

SHADOW_SUMMARY = PROJECT_ROOT / "reports/shadow_decision/shadow_decision_summary.json"
SHADOW_JOURNAL = PROJECT_ROOT / "reports/shadow_decision/shadow_decision_journal.csv"
DRY_RUN_JOURNAL = PROJECT_ROOT / "reports/dry_run_journal/dry_run_decision_journal.csv"
MARKET_SUMMARY = PROJECT_ROOT / "reports/market_intelligence/market_intelligence_summary.json"
MARKET_HISTORY = PROJECT_ROOT / "user_data/market_intelligence/scores/market_intelligence_history.csv"
ANTI_OVERFIT = PROJECT_ROOT / "reports/optimization/anti_overfit_summary.json"
SCORE_SUMMARY = PROJECT_ROOT / "reports/optimization/stable_profit_score_summary.json"
GATEKEEPER = PROJECT_ROOT / "reports/gatekeeper/gatekeeper_summary.json"
SAMPLE_VALIDATION = PROJECT_ROOT / "reports/sample_validation/sample_validation_summary.json"
RULES = PROJECT_ROOT / "configs/optimization_experiment_rules.yaml"

DECISION_EVENT_TYPES = {"signal_replay", "dry_run_trade"}
CLOSE_EVENT_TYPES = {"dry_run_trade_closed"}
HISTORY_FIELDS = [
    "timestamp",
    "status",
    "collection_status",
    "decision_status",
    "decision_grade_today",
    "forward_closed_total",
    "forward_closed_target",
    "forward_closed_rate_7d",
    "verified_consecutive_observation_days",
    "observation_days_target",
    "eta_days",
    "leading_events_today",
    "context_snapshots_today",
    "dry_run_running",
    "top_candidate",
    "best_experimental_candidate",
    "best_experimental_net_filter_value",
    "overfit_risk",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def event_key(row: dict[str, str]) -> str:
    trade_id = str(row.get("dry_run_trade_id") or "").strip()
    if trade_id:
        return f"trade:{trade_id}"
    return "|".join(
        str(row.get(field) or "")
        for field in ("event_type", "pair", "signal_time", "snapshot_time")
    )


def unique_baseline_events(
    rows: list[dict[str, str]],
    event_types: set[str],
    since: dt.datetime | None = None,
) -> list[dict[str, str]]:
    unique: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.get("candidate_name") != "baseline_nfi" or row.get("event_type") not in event_types:
            continue
        timestamp = parse_time(row.get("snapshot_time"))
        if since and (timestamp is None or timestamp < since):
            continue
        unique[event_key(row)] = row
    return list(unique.values())


def unique_closed_outcomes(
    rows: list[dict[str, str]],
    since: dt.datetime | None = None,
) -> list[dict[str, str]]:
    outcomes: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.get("candidate_name") != "baseline_nfi":
            continue
        is_close_event = row.get("event_type") in CLOSE_EVENT_TYPES
        has_close_value = row.get("dry_run_close_profit") not in ("", None)
        if not is_close_event and not has_close_value:
            continue
        timestamp = parse_time(row.get("snapshot_time"))
        if since and (timestamp is None or timestamp < since):
            continue
        outcomes[event_key(row)] = row
    return list(outcomes.values())


def unique_market_snapshots(rows: list[dict[str, str]], since: dt.datetime | None = None) -> int:
    timestamps = set()
    for row in rows:
        timestamp = parse_time(row.get("generated_at"))
        if timestamp is None or (since and timestamp < since):
            continue
        timestamps.add(timestamp.isoformat())
    return len(timestamps)


def summarize_sample_viability(sample: dict[str, Any], entry_target: int = 20) -> dict[str, Any]:
    expanded = [
        group
        for group in sample.get("groups", [])
        if str(group.get("group", "")).startswith("expanded_")
    ]
    reference = max(expanded, key=lambda group: as_int(group.get("days")), default={})
    reference_days = as_int(reference.get("days"))
    reference_entries = as_int(reference.get("trades_count"))
    entry_rate = round(reference_entries / reference_days, 6) if reference_days else 0.0
    return {
        "available": bool(expanded),
        "generated_at": sample.get("generated_at"),
        "pair_count": max((as_int(group.get("pair_count")) for group in expanded), default=0),
        "entries_180d": max(
            (as_int(group.get("trades_count")) for group in expanded if as_int(group.get("days")) == 180),
            default=0,
        ),
        "entries_365d": max(
            (as_int(group.get("trades_count")) for group in expanded if as_int(group.get("days")) == 365),
            default=0,
        ),
        "reference_days": reference_days,
        "reference_entries": reference_entries,
        "replay_entries_per_day": entry_rate,
        "projected_days_to_entry_target": math.ceil(entry_target / entry_rate) if entry_rate > 0 else None,
        "signal_viability_proven": any(as_int(group.get("trades_count")) > 0 for group in expanded),
        "profitability_proven": False,
        "runtime_config_untouched": sample.get("runtime_config_untouched") is True,
    }


def verified_consecutive_running_days(
    rows: list[dict[str, str]],
    today: dt.date,
    running_now: bool,
) -> int:
    latest_by_day: dict[dt.date, tuple[dt.datetime, bool]] = {}
    for row in rows:
        timestamp = parse_time(row.get("timestamp"))
        if timestamp is None:
            continue
        is_running = str(row.get("bot_status") or "").lower().startswith("running")
        previous = latest_by_day.get(timestamp.date())
        if previous is None or timestamp > previous[0]:
            latest_by_day[timestamp.date()] = (timestamp, is_running)
    latest_by_day[today] = (
        dt.datetime.combine(today, dt.time.max, tzinfo=dt.timezone.utc),
        running_now,
    )
    count = 0
    day = today
    while latest_by_day.get(day, (None, False))[1]:
        count += 1
        day -= dt.timedelta(days=1)
    return count


def estimate_eta_days(
    current_trades: int,
    trade_target: int,
    trades_per_day: float,
    observation_days: int,
    observation_target: int,
    collecting: bool,
) -> int | None:
    if not collecting:
        return None
    remaining_observation = max(0, observation_target - observation_days)
    remaining_trades = max(0, trade_target - current_trades)
    if remaining_trades and trades_per_day <= 0:
        return None
    trade_days = math.ceil(remaining_trades / trades_per_day) if remaining_trades else 0
    return max(remaining_observation, trade_days)


def age_hours(value: Any, now: dt.datetime) -> float | None:
    parsed = parse_time(value)
    if parsed is None:
        return None
    return round(max(0.0, (now - parsed).total_seconds() / 3600), 3)


def load_targets() -> dict[str, int]:
    rules = load_json(RULES, {})
    minimum = rules.get("minimum_evidence", {}) if isinstance(rules, dict) else {}
    return {
        "observation_days": as_int(minimum.get("shadow_days"), 14),
        "forward_closed_trades": as_int(minimum.get("forward_closed_trades"), 20),
    }


def choose_status(
    runtime: dict[str, Any],
    forward_closed: int,
    trade_target: int,
    rate_7d: float,
    observation_days: int,
    observation_target: int,
    quality_pass: bool,
) -> tuple[str, str, str]:
    running = bool(runtime.get("running"))
    safe = bool((runtime.get("safety") or {}).get("pass"))
    sample_ready = forward_closed >= trade_target and observation_days >= observation_target
    if not safe or not running:
        return "EVIDENCE_BLOCKED", "STOPPED_OR_UNSAFE", "NOT_READY"
    if not sample_ready and rate_7d <= 0:
        return "EVIDENCE_STARVED", "RUNNING", "NOT_READY"
    if not sample_ready:
        return "COLLECTING", "RUNNING", "NOT_READY"
    if not quality_pass:
        return "QUALITY_BLOCKED", "RUNNING", "TIME_ALONE_WILL_NOT_FIX_QUALITY"
    return "READY_FOR_SHADOW_REVIEW", "RUNNING", "READY_FOR_SHADOW_REVIEW"


def build_summary(now: dt.datetime | None = None) -> dict[str, Any]:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    today_start = dt.datetime.combine(now.date(), dt.time.min, tzinfo=dt.timezone.utc)
    rolling_start = today_start - dt.timedelta(days=6)

    runtime = dry_run_status()
    shadow = load_json(SHADOW_SUMMARY, {})
    market = load_json(MARKET_SUMMARY, {})
    anti = load_json(ANTI_OVERFIT, {})
    score = load_json(SCORE_SUMMARY, {})
    gate = load_json(GATEKEEPER, {})
    sample = load_json(SAMPLE_VALIDATION, {})
    targets = load_targets()
    shadow_rows = read_csv(SHADOW_JOURNAL)
    dry_run_rows = read_csv(DRY_RUN_JOURNAL)
    market_rows = read_csv(MARKET_HISTORY)

    leading_today = unique_baseline_events(shadow_rows, DECISION_EVENT_TYPES, today_start)
    leading_7d = unique_baseline_events(shadow_rows, DECISION_EVENT_TYPES, rolling_start)
    closed_today = unique_closed_outcomes(shadow_rows, today_start)
    closed_7d = unique_closed_outcomes(shadow_rows, rolling_start)
    closed_all = unique_closed_outcomes(shadow_rows)
    forward_closed = max(
        len(closed_all),
        as_int(shadow.get("forward_closed_trades")),
        as_int(shadow.get("recent_closed_trades_count")),
    )
    rate_7d = round(len(closed_7d) / 7, 6)
    observation_days = verified_consecutive_running_days(
        dry_run_rows,
        now.date(),
        bool(runtime.get("running")),
    )

    top = score.get("top_candidate") or {}
    experimental = score.get("best_experimental_candidate") or {}
    net_filter = as_float(experimental.get("net_filter_value"), float("-inf"))
    overfit_risk = str(anti.get("overfit_risk") or experimental.get("overfit_risk") or "UNKNOWN")
    improves_profit = as_float(experimental.get("profit_after_slippage")) > as_float(top.get("profit_after_slippage"))
    improves_drawdown = as_float(experimental.get("max_drawdown"), float("inf")) < as_float(top.get("max_drawdown"), float("inf"))
    quality_pass = net_filter >= 0 and overfit_risk != "HIGH" and (improves_profit or improves_drawdown)
    research_viability = summarize_sample_viability(sample, targets["forward_closed_trades"])

    status, collection_status, decision_status = choose_status(
        runtime,
        forward_closed,
        targets["forward_closed_trades"],
        rate_7d,
        observation_days,
        targets["observation_days"],
        quality_pass,
    )
    eta_days = estimate_eta_days(
        forward_closed,
        targets["forward_closed_trades"],
        rate_7d,
        observation_days,
        targets["observation_days"],
        bool(runtime.get("running")) and bool((runtime.get("safety") or {}).get("pass")),
    )
    if eta_days is not None:
        eta_reason = "Sample ETA is the slower of observation time and forward closed-trade throughput."
    elif not runtime.get("running"):
        eta_reason = "Evidence collection is stopped."
    elif not (runtime.get("safety") or {}).get("pass"):
        eta_reason = "The running collector failed the safety contract."
    else:
        eta_reason = "The collector is running, but the decision-grade closed-trade rate is zero."

    blockers: list[str] = []
    if not runtime.get("running"):
        blockers.append("DRY_RUN_STOPPED")
    if not (runtime.get("safety") or {}).get("pass"):
        blockers.append("RUNTIME_SAFETY_FAILED")
    if forward_closed < targets["forward_closed_trades"]:
        blockers.append("FORWARD_CLOSED_TRADES_BELOW_TARGET")
    if rate_7d <= 0 and forward_closed < targets["forward_closed_trades"]:
        blockers.append("ZERO_DECISION_GRADE_RATE")
    if observation_days < targets["observation_days"]:
        blockers.append("VERIFIED_CONSECUTIVE_OBSERVATION_DAYS_BELOW_TARGET")
    if overfit_risk == "HIGH":
        blockers.append("OVERFIT_RISK_HIGH")
    if net_filter < 0:
        blockers.append("EXPERIMENTAL_NET_FILTER_NOT_POSITIVE")
    if score.get("no_candidate_ready_for_shadow") is True:
        blockers.append("NO_CANDIDATE_READY_FOR_SHADOW")
    research_pair_universe_active = (
        research_viability["pair_count"] > 0
        and as_int(runtime.get("active_pair_count")) >= research_viability["pair_count"]
    )
    if not leading_7d and research_viability["signal_viability_proven"] and not research_pair_universe_active:
        blockers.append("VALIDATED_PAIR_UNIVERSE_NOT_IN_FORWARD_COLLECTION")

    if not runtime.get("running"):
        direction = "RESTORE_EVIDENCE_COLLECTION"
        profile = " -Profile evidence" if research_viability["signal_viability_proven"] else ""
        next_action = (
            "Run `powershell -NoProfile -ExecutionPolicy Bypass -File "
            f".\\scripts\\start-native-windows.ps1{profile}`, then rerun daily ops and verify one full scheduled cycle."
        )
    elif not leading_7d and not research_viability["signal_viability_proven"]:
        direction = "FIX_SIGNAL_VIABILITY_BEFORE_MORE_FACTORS"
        next_action = "Run a research-only signal-viability experiment with a broader NFI-aligned pair universe; keep the production dry-run unchanged."
    elif not leading_7d and not research_pair_universe_active:
        direction = "ACTIVATE_VALIDATED_PAIR_UNIVERSE_FOR_FORWARD_EVIDENCE"
        next_action = (
            "Restart the collector with `powershell -NoProfile -ExecutionPolicy Bypass -File "
            ".\\scripts\\start-native-windows.ps1 -Profile evidence -Replace`; do not overwrite runtime config, change NFI, or enable live trading."
        )
    elif not leading_7d:
        direction = "COLLECT_EXPANDED_UNIVERSE_FORWARD_OUTCOMES"
        next_action = "Keep the safe 20-pair dry-run running until signals produce closed forward outcomes; do not add factors meanwhile."
    elif rate_7d <= 0:
        direction = "COLLECT_OUTCOME_LABELS_BEFORE_MORE_OPTIMIZATION"
        next_action = "Keep the safe dry-run running until observed signals close and produce outcome labels; do not add more factors meanwhile."
    elif not quality_pass:
        direction = "IMPROVE_SIZING_OR_FILTER_ECONOMICS"
        next_action = "Use counterfactual outcomes to improve net filter value or drawdown without reducing slippage-adjusted profit."
    else:
        direction = "REVIEW_SHADOW_PROMOTION"
        next_action = "Perform a manual shadow-promotion review; live trading remains blocked."

    snapshot_confidence = ((market.get("snapshot") or {}).get("confidence") or {})
    summary = {
        "generated_at": now.isoformat(timespec="seconds"),
        "status": status,
        "collection_status": collection_status,
        "decision_status": decision_status,
        "today": {
            "decision_grade_closed_trades": len(closed_today),
            "leading_signal_or_trade_events": len(leading_today),
            "point_in_time_context_snapshots": unique_market_snapshots(market_rows, today_start),
        },
        "rolling_7d": {
            "decision_grade_closed_trades": len(closed_7d),
            "decision_grade_trades_per_calendar_day": rate_7d,
            "leading_signal_or_trade_events": len(leading_7d),
            "point_in_time_context_snapshots": unique_market_snapshots(market_rows, rolling_start),
        },
        "cumulative": {
            "forward_closed_trades": forward_closed,
            "verified_consecutive_observation_days": observation_days,
            "offline_historical_rows": as_int(anti.get("historical_sample_size")),
            "point_in_time_snapshots": unique_market_snapshots(market_rows),
        },
        "targets": targets,
        "eta": {
            "days": eta_days,
            "status": str(eta_days) if eta_days is not None else "UNBOUNDED_AT_CURRENT_RATE",
            "reason": eta_reason,
        },
        "quality": {
            "top_candidate": top.get("candidate_id", "MISSING"),
            "best_experimental_candidate": experimental.get("candidate_id", "MISSING"),
            "best_experimental_net_filter_value": experimental.get("net_filter_value"),
            "best_experimental_profit_after_slippage": experimental.get("profit_after_slippage"),
            "best_experimental_max_drawdown": experimental.get("max_drawdown"),
            "improves_profit_vs_baseline": improves_profit,
            "improves_drawdown_vs_baseline": improves_drawdown,
            "overfit_risk": overfit_risk,
            "quality_gate_pass": quality_pass,
            "data_confidence": snapshot_confidence.get("data_confidence"),
            "factor_group_coverage": snapshot_confidence.get("factor_group_coverage"),
            "data_confidence_is_profitability_confidence": False,
        },
        "research_signal_viability": research_viability,
        "freshness_hours": {
            "shadow_summary": age_hours(shadow.get("generated_at"), now),
            "market_intelligence": age_hours(market.get("generated_at"), now),
            "anti_overfit": age_hours(anti.get("generated_at"), now),
            "stable_profit_score": age_hours(score.get("generated_at"), now),
            "sample_validation": age_hours(sample.get("generated_at"), now),
        },
        "blockers": blockers,
        "profitability_direction": direction,
        "next_action": next_action,
        "gatekeeper_status": gate.get("status", "MISSING"),
        "git": git_info(),
        "safety": {
            "runtime_safe": bool((runtime.get("safety") or {}).get("pass")),
            "dry_run_running": bool(runtime.get("running")),
            "dry_run_status": runtime.get("status"),
            "running_mode": runtime.get("running_mode"),
            "active_config": runtime.get("active_config"),
            "active_pair_count": as_int(runtime.get("active_pair_count")),
            "research_pair_universe_active": research_pair_universe_active,
            "real_trading_allowed": False,
            "controls_orders": False,
        },
    }
    return summary


def append_history(summary: dict[str, Any]) -> None:
    row = {
        "timestamp": summary["generated_at"],
        "status": summary["status"],
        "collection_status": summary["collection_status"],
        "decision_status": summary["decision_status"],
        "decision_grade_today": summary["today"]["decision_grade_closed_trades"],
        "forward_closed_total": summary["cumulative"]["forward_closed_trades"],
        "forward_closed_target": summary["targets"]["forward_closed_trades"],
        "forward_closed_rate_7d": summary["rolling_7d"]["decision_grade_trades_per_calendar_day"],
        "verified_consecutive_observation_days": summary["cumulative"]["verified_consecutive_observation_days"],
        "observation_days_target": summary["targets"]["observation_days"],
        "eta_days": summary["eta"]["days"] if summary["eta"]["days"] is not None else "",
        "leading_events_today": summary["today"]["leading_signal_or_trade_events"],
        "context_snapshots_today": summary["today"]["point_in_time_context_snapshots"],
        "dry_run_running": summary["safety"]["dry_run_running"],
        "top_candidate": summary["quality"]["top_candidate"],
        "best_experimental_candidate": summary["quality"]["best_experimental_candidate"],
        "best_experimental_net_filter_value": summary["quality"]["best_experimental_net_filter_value"],
        "overfit_risk": summary["quality"]["overfit_risk"],
    }
    exists = HISTORY.exists() and HISTORY.stat().st_size > 0
    with HISTORY.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def render_report(summary: dict[str, Any]) -> str:
    eta = summary["eta"]["status"]
    return "\n".join(
        [
            "# Evidence Throughput Controller",
            "",
            f"Generated: `{summary['generated_at']}`",
            f"Status: `{summary['status']}`",
            f"Collection: `{summary['collection_status']}`",
            f"Decision: `{summary['decision_status']}`",
            "",
            "## Evidence Produced Today (UTC)",
            "",
            f"- Decision-grade closed trades: `{summary['today']['decision_grade_closed_trades']}`",
            f"- Leading signal/trade events: `{summary['today']['leading_signal_or_trade_events']}`",
            f"- Point-in-time context snapshots: `{summary['today']['point_in_time_context_snapshots']}`",
            "",
            "## Decision ETA",
            "",
            f"- Forward closed trades: `{summary['cumulative']['forward_closed_trades']} / {summary['targets']['forward_closed_trades']}`",
            f"- Verified consecutive observation days: `{summary['cumulative']['verified_consecutive_observation_days']} / {summary['targets']['observation_days']}`",
            f"- Rolling seven-day closed-trade rate: `{summary['rolling_7d']['decision_grade_trades_per_calendar_day']} / day`",
            f"- ETA: `{eta}`",
            "",
            "## Profitability Quality",
            "",
            f"- Baseline: `{summary['quality']['top_candidate']}`",
            f"- Best experimental candidate: `{summary['quality']['best_experimental_candidate']}`",
            f"- Experimental net filter value: `{summary['quality']['best_experimental_net_filter_value']}`",
            f"- Overfit risk: `{summary['quality']['overfit_risk']}`",
            f"- Quality gate passed: `{summary['quality']['quality_gate_pass']}`",
            "- Data confidence is profitability confidence: `False`",
            f"- Research-only expanded-pair entries: `{summary['research_signal_viability']['entries_180d']} / 180d`; `{summary['research_signal_viability']['entries_365d']} / 365d`",
            "- Research signal viability is forward profitability: `False`",
            "",
            f"Blockers: `{';'.join(summary['blockers']) or 'NONE'}`",
            f"Direction: `{summary['profitability_direction']}`",
            f"Next action: {summary['next_action']}",
            "",
            "This controller is read-only with respect to strategy and orders. Gatekeeper remains authoritative.",
        ]
    ) + "\n"


def render_context(summary: dict[str, Any]) -> str:
    eta = summary["eta"]["status"]
    freshness = summary["freshness_hours"]
    return "\n".join(
        [
            "# Current Decision Context",
            "",
            f"Generated: `{summary['generated_at']}`",
            f"Git: `{summary['git']['branch']}@{summary['git']['commit']}`",
            "",
            "## Bottom Line",
            "",
            f"- Evidence throughput: `{summary['status']}`",
            f"- Dry-run: `{summary['safety']['dry_run_status']}` via `{summary['safety']['running_mode']}` with `{summary['safety']['active_pair_count']} pairs`",
            f"- Gatekeeper: `{summary['gatekeeper_status']}`",
            f"- Shadow decision: `{summary['decision_status']}`",
            f"- Profitability direction: `{summary['profitability_direction']}`",
            "",
            "## Today (UTC)",
            "",
            "| evidence class | produced today | decision meaning |",
            "|---|---:|---|",
            f"| Decision-grade closed forward trades | {summary['today']['decision_grade_closed_trades']} | Primary outcome sample |",
            f"| Leading NFI signal/trade events | {summary['today']['leading_signal_or_trade_events']} | Signal viability only |",
            f"| Point-in-time context snapshots | {summary['today']['point_in_time_context_snapshots']} | Market context only |",
            "",
            "## Time to Decision",
            "",
            f"- Forward closed trades: `{summary['cumulative']['forward_closed_trades']} / {summary['targets']['forward_closed_trades']}`",
            f"- Verified consecutive observation days: `{summary['cumulative']['verified_consecutive_observation_days']} / {summary['targets']['observation_days']}`",
            f"- Decision-grade throughput: `{summary['rolling_7d']['decision_grade_trades_per_calendar_day']} trades/day` over seven calendar days",
            f"- ETA: `{eta}`",
            f"- ETA basis: {summary['eta']['reason']}",
            "",
            "## Profitability Evidence",
            "",
            f"- Offline historical rows: `{summary['cumulative']['offline_historical_rows']}`",
            f"- Current baseline: `{summary['quality']['top_candidate']}`",
            f"- Best experimental candidate: `{summary['quality']['best_experimental_candidate']}`",
            f"- Experimental net filter value: `{summary['quality']['best_experimental_net_filter_value']}`",
            f"- Improves slippage-adjusted profit: `{summary['quality']['improves_profit_vs_baseline']}`",
            f"- Improves drawdown: `{summary['quality']['improves_drawdown_vs_baseline']}`",
            f"- Overfit risk: `{summary['quality']['overfit_risk']}`",
            f"- Data confidence: `{summary['quality']['data_confidence']}` with factor-group coverage `{summary['quality']['factor_group_coverage']}`",
            "- Data confidence proves profitability: `False`",
            f"- Research-only expanded universe: `{summary['research_signal_viability']['pair_count']} pairs`",
            f"- Research replay entries: `{summary['research_signal_viability']['entries_180d']} / 180d`; `{summary['research_signal_viability']['entries_365d']} / 365d`",
            f"- Research replay entry rate: `{summary['research_signal_viability']['replay_entries_per_day']} / day`",
            f"- Projected days to {summary['targets']['forward_closed_trades']} entries at the research replay rate: `{summary['research_signal_viability']['projected_days_to_entry_target']}` (not a decision ETA)",
            "- Research signal viability proves forward profitability: `False`",
            "",
            "## Freshness",
            "",
            f"- Shadow summary age: `{freshness['shadow_summary']} hours`",
            f"- Market-intelligence age: `{freshness['market_intelligence']} hours`",
            f"- Anti-overfit evidence age: `{freshness['anti_overfit']} hours`",
            f"- Stable-profit score age: `{freshness['stable_profit_score']} hours`",
            f"- Sample-validation evidence age: `{freshness['sample_validation']} hours`",
            "",
            "## Blockers",
            "",
            *[f"- `{blocker}`" for blocker in summary["blockers"]],
            "",
            "## Next Action",
            "",
            summary["next_action"],
            "",
            "## Safety Boundary",
            "",
            "Allowed: dry-run, shadow observation, research-only replay, and Binance Spot Testnet practice.",
            "",
            "Forbidden: real-money trading, futures, margin, leverage, shorting, public FreqUI, credential persistence, or automatic live promotion.",
            "",
            "Sources: `reports/evidence_throughput/evidence_throughput_summary.json`, `reports/shadow_decision/shadow_decision_summary.json`, `reports/optimization/stable_profit_score_summary.json`, and live `dry_run_status.py`.",
        ]
    ) + "\n"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    summary = build_summary()
    write_json(SUMMARY, summary)
    REPORT.write_text(render_report(summary), encoding="utf-8")
    CONTEXT.write_text(render_context(summary), encoding="utf-8")
    append_history(summary)
    phase_record(
        "evidence_throughput_controller",
        summary["status"],
        "Evidence throughput and decision ETA generated.",
        {
            "decision_grade_today": summary["today"]["decision_grade_closed_trades"],
            "rate_7d": summary["rolling_7d"]["decision_grade_trades_per_calendar_day"],
            "eta": summary["eta"]["status"],
        },
    )
    print(f"EVIDENCE_THROUGHPUT_STATUS={summary['status']}")
    print(f"DECISION_GRADE_TODAY={summary['today']['decision_grade_closed_trades']}")
    print(f"DECISION_ETA_DAYS={summary['eta']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
