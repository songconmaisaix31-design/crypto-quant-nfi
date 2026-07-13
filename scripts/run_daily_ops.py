#!/usr/bin/env python3
from __future__ import annotations

import csv

from ops_common import PROJECT_ROOT, git_info, load_json, phase_record, run_cmd, utc_now, write_json


OUT = PROJECT_ROOT / "reports/ops/daily"
SUMMARY = OUT / "daily_ops_summary.json"
REPORT = OUT / "daily_ops_report.md"
LOGS = OUT / "daily_ops_logs.txt"
HISTORY = OUT / "daily_ops_history.csv"


COMMANDS = [
    ("status_native", ["bash", "scripts/status-native.sh"], False),
    ("ensure_dry_run_running", ["bash", "scripts/ensure-dry-run-running.sh"], False),
    ("status_testnet", ["bash", "scripts/status-testnet.sh"], False),
    ("market_intelligence_credentials", ["bash", "scripts/check-market-intelligence-credentials.sh"], False),
    ("collect_market_intelligence", ["bash", "scripts/collect-market-intelligence.sh"], False),
    ("build_market_intelligence_features", ["bash", "scripts/build-market-intelligence-features.sh"], False),
    ("market_intelligence_shadow_journal", ["bash", "scripts/market-intelligence-shadow-journal.sh"], False),
    ("market_intelligence_daily_report", ["bash", "scripts/market-intelligence-daily-report.sh"], False),
    ("gatekeeper", ["bash", "scripts/gatekeeper.sh"], True),
    ("pre_live_gate", ["bash", "scripts/pre-live-gate.sh"], False),
    ("testnet_gate", ["bash", "scripts/testnet-gate.sh"], True),
    ("micro_live_readiness", ["bash", "scripts/micro-live-readiness.sh"], True),
    ("build_market_state", ["bash", "scripts/build-market-state.sh"], False),
    ("shadow_signal_check", ["bash", "scripts/shadow-signal-check.sh"], False),
    ("shadow_decision_journal", ["bash", "scripts/shadow-decision-journal.sh"], False),
    ("shadow_decision_daily_report", ["bash", "scripts/shadow-decision-daily-report.sh"], False),
    ("dry_run_journal", ["bash", "scripts/dry-run-decision-journal.sh"], False),
    ("emergency_stop_check", ["bash", "scripts/emergency-stop-check.sh"], True),
    ("audit_verify", ["bash", "scripts/audit-verify.sh"], True),
    ("secret_scan", ["bash", "scripts/secret-scan.sh"], True),
]

CONTEXT_FINALIZER = ("evidence_throughput_controller", ["bash", "scripts/evidence-throughput-controller.sh"], False)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    logs = [f"generated_at={utc_now()}", f"git={git_info()}"]
    blocked = False
    for name, cmd, safety_critical in COMMANDS:
        result = run_cmd(cmd, timeout=240)
        result["name"] = name
        result["safety_critical"] = safety_critical
        tolerated_blocked = name in {"pre_live_gate", "micro_live_readiness"} and result["exit_code"] in (0, 2)
        if safety_critical and result["exit_code"] not in (0,) and not tolerated_blocked:
            blocked = True
        results.append(result)
        logs.append(f"$ {result['command']}\nexit={result['exit_code']}\n{result['stdout']}\n{result['stderr']}")
        if blocked:
            break
    name, cmd, safety_critical = CONTEXT_FINALIZER
    result = run_cmd(cmd, timeout=240)
    result["name"] = name
    result["safety_critical"] = safety_critical
    results.append(result)
    logs.append(f"$ {result['command']}\nexit={result['exit_code']}\n{result['stdout']}\n{result['stderr']}")
    if result["exit_code"] != 0:
        blocked = True
    dry_run_check = load_json(PROJECT_ROOT / "reports/ops/daily/dry_run_running_check.json", {})
    forward_evidence_blocked = bool(dry_run_check.get("forward_evidence_blocked"))
    status = "BLOCKED" if blocked else "PASS"
    summary = {
        "generated_at": utc_now(),
        "status": status,
        "git": git_info(),
        "results": results,
        "testnet_key_required": False,
        "dry_run_running": bool(dry_run_check.get("running")),
        "dry_run_running_mode": dry_run_check.get("running_mode", "unknown"),
        "forward_evidence_blocked": forward_evidence_blocked,
        "forward_evidence_blocked_reason": "dry-run is not running" if forward_evidence_blocked else "",
        "real_trading_allowed": False,
        "micro_live_allowed": False,
    }
    write_json(SUMMARY, summary)
    LOGS.write_text("\n\n".join(logs) + "\n", encoding="utf-8")
    rows = [{"timestamp": summary["generated_at"], "status": status, "command": r["name"], "exit_code": r["exit_code"]} for r in results]
    exists = HISTORY.exists()
    with HISTORY.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "status", "command", "exit_code"])
        if not exists:
            writer.writeheader()
        writer.writerows(rows)
    lines = ["# Daily Ops Report", "", f"Status: `{status}`", ""]
    lines += [
        f"- Dry-run running: `{summary['dry_run_running']}`",
        f"- Dry-run mode: `{summary['dry_run_running_mode']}`",
        f"- Forward evidence blocked: `{summary['forward_evidence_blocked']}`",
        "",
    ]
    if forward_evidence_blocked:
        lines += [
            "**Forward evidence collection is blocked because dry-run is not running.**",
            "",
        ]
    lines += ["| command | exit | status |", "|---|---:|---|"]
    for r in results:
        lines.append(f"| `{r['name']}` | {r['exit_code']} | `{r['status']}` |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    phase_record("daily_ops", status, f"Daily ops completed with status {status}.", {"commands": len(results)})
    print(f"DAILY_OPS_STATUS={status}")
    return 0 if status != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
