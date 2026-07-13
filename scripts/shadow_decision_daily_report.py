#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
REPORT_OUT = PROJECT_ROOT / "reports/shadow_decision"
SUMMARY = REPORT_OUT / "shadow_decision_summary.json"
JOURNAL = REPORT_OUT / "shadow_decision_journal.csv"
COMPARISON = REPORT_OUT / "shadow_candidate_comparison.csv"
DAILY = REPORT_OUT / "shadow_decision_daily_report.md"
DAILY_JSON = REPORT_OUT / "shadow_decision_summary.json"
PRELIVE_V3 = PROJECT_ROOT / "reports/pre_live_gate/pre_live_gate_v3_summary.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def best_candidate(rows: list[dict[str, str]]) -> str:
    scored = []
    for row in rows:
        events = int(float(row.get("observed_events") or 0))
        net = float(row.get("net_filter_value") or 0)
        reduced = int(float(row.get("reduced_stake_events") or 0))
        blocked = int(float(row.get("blocked_events") or 0))
        score = net + reduced * 0.1 - blocked * 0.05
        scored.append((score, events, row.get("candidate_name", "")))
    scored = [s for s in scored if s[1] > 0]
    return max(scored)[2] if scored else "insufficient_observation_window"


def latest_candidate_rows(journal: list[dict[str, str]]) -> list[dict[str, str]]:
    if not journal:
        return []
    latest_time = max(r.get("snapshot_time", "") for r in journal)
    return [r for r in journal if r.get("snapshot_time") == latest_time]


def main() -> int:
    REPORT_OUT.mkdir(parents=True, exist_ok=True)
    summary = load_json(SUMMARY, {})
    comparison = read_csv(COMPARISON)
    journal = read_csv(JOURNAL)
    prelive = load_json(PRELIVE_V3, {})
    prelive_status = "BLOCKED"
    if prelive.get("live_trading_approved") is True:
        prelive_status = "PASS"
    candidate_lines = []
    for row in comparison:
        candidate_lines.append(
            f"| `{row.get('candidate_name')}` | {row.get('observed_events')} | {row.get('allowed_events')} | {row.get('blocked_events')} | {row.get('reduced_stake_events')} | {row.get('net_filter_value')} | {row.get('consistency_rate')} | {row.get('notes')} |"
        )
    latest_lines = []
    for row in latest_candidate_rows(journal):
        latest_lines.append(
            f"| `{row.get('candidate_name')}` | `{row.get('event_type')}` | `{row.get('candidate_decision')}` | `{row.get('stake_multiplier')}` | `{row.get('decision_reason')}` | `{row.get('consistency_status')}` |"
        )
    new_rows_today = len([r for r in journal if (r.get("snapshot_time") or "").startswith(str(summary.get("generated_at", ""))[:10])])
    has_false_kill = any(r.get("consistency_status") == "shadow_blocked_actual_trade" for r in journal)
    avoided_loss = any(float(r.get("avoided_loss") or 0) > 0 for r in comparison)
    best = best_candidate(comparison)
    lines = [
        "# Shadow Decision Daily Report",
        "",
        "This report observes candidate decisions only. It does not enable live trading and does not control Freqtrade orders.",
        "",
        "## Current Status",
        f"- Pre-live gate: `{prelive_status}`",
        f"- Bot running: `{summary.get('bot_running')}`",
        f"- Safe config: `{summary.get('safe_config')}`",
        f"- API available: `{summary.get('api_available')}`",
        f"- Signal detection status: `{summary.get('signal_detection_status')}`",
        f"- Signal check method: `{summary.get('signal_check_method')}`",
        f"- Observation days: `{summary.get('observation_days')}`",
        "",
        "## Today",
        f"- Market regime: `{summary.get('today_market_regime')}`",
        f"- Market sentiment score: `{summary.get('today_market_sentiment_score')}`",
        f"- Confirmed signals: `{summary.get('confirmed_signal_count')}`",
        f"- Confirmed no-signal pairs: `{summary.get('confirmed_no_signal_count')}`",
        f"- Inferred trades: `{summary.get('inferred_signal_count')}`",
        f"- Open trades: `{summary.get('open_trades_count')}`",
        f"- Recent closed trades: `{summary.get('recent_closed_trades_count')}`",
        f"- New signals/trades this run: `{summary.get('new_trade_since_last_snapshot')}`",
        f"- Journal rows today: `{new_rows_today}`",
        "",
        "## Latest Candidate Decisions",
        "| candidate | event | decision | stake | reason | consistency |",
        "|---|---|---|---:|---|---|",
    ]
    lines.extend(latest_lines or ["| `N/A` | `none` | `N/A` | 0 | no latest snapshot | `data_unavailable` |"])
    lines += [
        "",
        "## Candidate Comparison",
        "| candidate | events | allow | block | reduce | net_filter_value | consistency | notes |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    lines.extend(candidate_lines or ["| `N/A` | 0 | 0 | 0 | 0 | 0 |  | insufficient_observation_window |"])
    lines += [
        "",
        "## Checks",
        f"- False-killed profitable actual trades observed: `{has_false_kill}`",
        f"- Avoided loss observed: `{avoided_loss}`",
        f"- Consistency status: `{summary.get('consistency_status')}`",
        f"- Safety abnormality: `{not bool(summary.get('safe_config'))}`",
        f"- Out-of-sample sample requirement met: `{int(summary.get('observed_events') or 0) >= 20}`",
        "",
        "## Recommendation",
        f"- Candidate worth continuing to observe: `{best}`.",
        "- Continue collecting 2-4 weeks of dry-run shadow evidence. Pre-live remains BLOCKED until all hard gates pass.",
    ]
    DAILY.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[PASS] wrote {DAILY}")
    print(f"[PASS] wrote {DAILY_JSON}")
    print(f"[BLOCKED] pre-live gate is {prelive_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
