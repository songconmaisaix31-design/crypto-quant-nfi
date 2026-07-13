#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path
from typing import Any

from dry_run_status import dry_run_status
from ops_common import PROJECT_ROOT, load_json, phase_record, read_status, run_cmd, utc_now, write_json


OUT = PROJECT_ROOT / "reports/forward_evidence"
SUMMARY = OUT / "watch_summary.json"
REPORT = OUT / "watch_report.md"
HISTORY = OUT / "watch_history.csv"
LOGS = OUT / "watch_logs.txt"

FIELDS = [
    "snapshot_time",
    "dry_run_status",
    "bot_running",
    "freq_ui_status",
    "signal_detection_status",
    "confirmed_signal_count",
    "new_signal_since_last_snapshot",
    "new_trade_since_last_snapshot",
    "recent_closed_trades_count",
    "gatekeeper_status",
    "pre_live_status",
    "micro_live_status",
    "safety_status",
    "notes",
]


def append_history(row: dict[str, Any]) -> None:
    exists = HISTORY.exists() and HISTORY.stat().st_size > 0
    with HISTORY.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in FIELDS})


def snapshot(index: int, restart_dry_run: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    commands: list[dict[str, Any]] = []
    commands.append(run_cmd(["bash", "scripts/status-native.sh"], timeout=120) | {"name": "status_native"})
    ensure_cmd = ["bash", "scripts/ensure-dry-run-running.sh"]
    if restart_dry_run:
        ensure_cmd.append("--start")
    commands.append(run_cmd(ensure_cmd, timeout=240) | {"name": "ensure_dry_run_running"})
    commands.append(run_cmd(["bash", "scripts/shadow-signal-check.sh"], timeout=420) | {"name": "shadow_signal_check"})
    commands.append(run_cmd(["bash", "scripts/shadow-decision-journal.sh"], timeout=300) | {"name": "shadow_decision_journal"})
    commands.append(run_cmd(["bash", "scripts/gatekeeper.sh"], timeout=240) | {"name": "gatekeeper"})

    dry = dry_run_status()
    shadow = load_json(PROJECT_ROOT / "reports/shadow_decision/shadow_decision_summary.json", {})
    gate = load_json(PROJECT_ROOT / "reports/gatekeeper/gatekeeper_summary.json", {})
    micro = load_json(PROJECT_ROOT / "reports/micro_live_readiness/micro_live_readiness_summary.json", {})
    row = {
        "snapshot_time": utc_now(),
        "dry_run_status": dry["status"],
        "bot_running": dry["running"],
        "freq_ui_status": "reachable" if dry["api_health"].get("reachable") else "unreachable",
        "signal_detection_status": shadow.get("signal_detection_status", "MISSING"),
        "confirmed_signal_count": int(shadow.get("confirmed_signal_count") or 0),
        "new_signal_since_last_snapshot": int(shadow.get("new_signal_since_last_snapshot") or 0),
        "new_trade_since_last_snapshot": int(shadow.get("new_trade_since_last_snapshot") or 0),
        "recent_closed_trades_count": int(shadow.get("recent_closed_trades_count") or 0),
        "gatekeeper_status": gate.get("status", "MISSING"),
        "pre_live_status": read_status(PROJECT_ROOT / "reports/pre_live_gate/pre_live_gate_summary.json"),
        "micro_live_status": micro.get("status", "BLOCKED"),
        "safety_status": "PASS" if dry["safety"]["pass"] else "FAIL",
        "notes": "snapshot only; no restart" if not restart_dry_run else "explicit restart flag used",
    }
    append_history(row)
    return row, commands


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshots", type=int, default=3)
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--restart-dry-run", action="store_true")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    logs: list[str] = [f"generated_at={utc_now()}"]
    for index in range(args.snapshots):
        row, commands = snapshot(index, args.restart_dry_run)
        rows.append(row)
        logs.append(f"snapshot={index + 1} row={row}")
        for command in commands:
            logs.append(f"$ {command['command']}\nexit={command['exit_code']}\n{command['stdout']}\n{command['stderr']}")
        if index < args.snapshots - 1:
            time.sleep(args.interval_seconds)

    latest = rows[-1] if rows else {}
    status = "PASS" if latest.get("bot_running") else "BLOCKED"
    summary = {
        "generated_at": utc_now(),
        "status": status,
        "snapshots": args.snapshots,
        "interval_seconds": args.interval_seconds,
        "restart_dry_run": args.restart_dry_run,
        "latest": latest,
        "real_trading_allowed": False,
        "micro_live_allowed": False,
    }
    write_json(SUMMARY, summary)
    LOGS.write_text("\n\n".join(logs) + "\n", encoding="utf-8")
    lines = [
        "# Forward Evidence Watch Report",
        "",
        f"Status: `{status}`",
        f"Snapshots: `{args.snapshots}`",
        f"Interval seconds: `{args.interval_seconds}`",
        f"Restart dry-run: `{args.restart_dry_run}`",
        "",
        "| snapshot_time | dry_run_status | bot_running | signal_detection_status | new_signal | new_trade | closed_trades | gatekeeper | micro_live |",
        "|---|---|---:|---|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['snapshot_time']}` | `{row['dry_run_status']}` | `{row['bot_running']}` | "
            f"`{row['signal_detection_status']}` | {row['new_signal_since_last_snapshot']} | "
            f"{row['new_trade_since_last_snapshot']} | {row['recent_closed_trades_count']} | "
            f"`{row['gatekeeper_status']}` | `{row['micro_live_status']}` |"
        )
    if latest and not latest.get("bot_running"):
        lines += ["", "Forward evidence collection remains blocked because dry-run is not running."]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    phase_record("forward_evidence_watch", status, "Forward evidence watch completed.", {"snapshots": len(rows), "bot_running": latest.get("bot_running")})
    print(f"FORWARD_EVIDENCE_WATCH={status}")
    return 0 if status != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
