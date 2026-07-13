#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from dry_run_status import dry_run_status
from ops_common import PROJECT_ROOT, phase_record, utc_now, write_json


OUT = PROJECT_ROOT / "reports/ops/daily"
SUMMARY = OUT / "dry_run_running_check.json"
REPORT = OUT / "dry_run_running_check.md"


def write_outputs(status: dict, action: str, start_exit_code: int | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at": utc_now(),
        "status": status["status"],
        "running": status["running"],
        "running_mode": status["running_mode"],
        "forward_evidence_blocked": status["forward_evidence_blocked"],
        "action": action,
        "start_exit_code": start_exit_code,
        "safety": status["safety"],
        "systemd_system": status["systemd_system"],
        "systemd_user": status["systemd_user"],
        "freqtrade_trade_processes": status["freqtrade_trade_processes"],
        "hidden_windows_wsl_carrier_detected": status["hidden_windows_wsl_carrier"]["detected"],
        "api_health": status["api_health"],
        "real_trading_allowed": False,
        "micro_live_allowed": False,
    }
    write_json(SUMMARY, summary)
    lines = [
        "# Dry-run Running Check",
        "",
        f"Status: `{summary['status']}`",
        f"Running: `{summary['running']}`",
        f"Running mode: `{summary['running_mode']}`",
        f"Forward evidence blocked: `{summary['forward_evidence_blocked']}`",
        f"Action: `{summary['action']}`",
        "",
    ]
    if summary["forward_evidence_blocked"]:
        lines.append("Forward evidence collection is blocked because dry-run is not running.")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    phase_record("ensure_dry_run_running", "PASS" if summary["running"] else "NEED_START", "Dry-run running check completed.", summary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", action="store_true", help="Explicitly start dry-run using existing safe native start script.")
    args = parser.parse_args()

    status = dry_run_status()
    if not status["safety"]["pass"]:
        write_outputs(status, "BLOCKED_UNSAFE_RUNTIME")
        print("DRY_RUN_UNSAFE")
        return 2
    if status["running"]:
        write_outputs(status, "ALREADY_RUNNING")
        print("DRY_RUN_RUNNING")
        print(f"DRY_RUN_MODE={status['running_mode']}")
        return 0
    if not args.start:
        write_outputs(status, "NEED_START")
        print("DRY_RUN_STOPPED")
        print("NEED_START")
        return 0

    proc = subprocess.run(["bash", "scripts/start-native.sh"], cwd=PROJECT_ROOT, text=True, capture_output=True)
    refreshed = dry_run_status()
    write_outputs(refreshed, "START_ATTEMPTED", proc.returncode)
    print("START_ATTEMPTED")
    print(f"START_EXIT_CODE={proc.returncode}")
    print("DRY_RUN_RUNNING" if refreshed["running"] else "DRY_RUN_STOPPED")
    return 0 if refreshed["running"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

