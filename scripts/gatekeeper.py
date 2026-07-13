#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ops_common import PROJECT_ROOT, load_json, phase_record, read_status, runtime_safety, testnet_config_safe, utc_now, write_csv, write_json


OUT = PROJECT_ROOT / "reports/gatekeeper"
SUMMARY = OUT / "gatekeeper_summary.json"
REPORT = OUT / "gatekeeper_report.md"
MATRIX = OUT / "gatekeeper_matrix.csv"
LOGS = OUT / "gatekeeper_logs.txt"
SYSTEM_STATE = PROJECT_ROOT / "user_data/gates/system_state.json"


def evidence(path: str) -> dict[str, Any]:
    p = PROJECT_ROOT / path
    return {"path": path, "exists": p.exists(), "status": read_status(p) if p.suffix == ".json" else ("PRESENT" if p.exists() else "MISSING")}


def matrix_row(check: str, passed: bool, severity: str, evidence_data: Any, message: str) -> dict[str, Any]:
    return {
        "check": check,
        "status": "PASS" if passed else "FAIL",
        "severity": severity,
        "message": message,
        "evidence": json.dumps(evidence_data, ensure_ascii=False, default=str),
    }


def numeric(data: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        value = data
        for part in key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(value, (int, float)):
            return float(value)
    return default


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    system_state_dir = SYSTEM_STATE.parent
    system_state_dir.mkdir(parents=True, exist_ok=True)

    runtime = runtime_safety()
    testnet_cfg = testnet_config_safe()
    endpoint = load_json(PROJECT_ROOT / "reports/testnet_run/testnet_endpoint_audit.json", {})
    emergency = load_json(PROJECT_ROOT / "reports/micro_live_readiness/emergency_stop_check_summary.json", {})
    prelive = load_json(PROJECT_ROOT / "reports/pre_live_gate/pre_live_gate_summary.json", {})
    prelive_v3 = load_json(PROJECT_ROOT / "reports/pre_live_gate/pre_live_gate_v3_summary.json", {})
    testnet_gate = load_json(PROJECT_ROOT / "reports/testnet_gate/testnet_gate_summary.json", {})
    micro = load_json(PROJECT_ROOT / "reports/micro_live_readiness/micro_live_readiness_summary.json", {})
    testnet_run = load_json(PROJECT_ROOT / "reports/testnet_run/testnet_run_summary.json", {})
    shadow = load_json(PROJECT_ROOT / "reports/shadow_decision/shadow_decision_summary.json", {})
    decision_v2 = load_json(PROJECT_ROOT / "reports/decision_engine_v2/decision_engine_v2_summary.json", {})
    market_state = load_json(PROJECT_ROOT / "user_data/market_state/market_state_latest.json", {})
    signal_snapshot = load_json(PROJECT_ROOT / "user_data/shadow_decision/latest_signal_snapshot.json", {})
    shadow_snapshot = load_json(PROJECT_ROOT / "user_data/shadow_decision/latest_shadow_snapshot.json", {})
    dry_run_check = load_json(PROJECT_ROOT / "reports/ops/daily/dry_run_running_check.json", {})

    evidence_files = [
        "reports/pre_live_gate/pre_live_gate_summary.json",
        "reports/pre_live_gate/pre_live_gate_v2_evidence_update.md",
        "reports/pre_live_gate/pre_live_gate_shadow_evidence_update.md",
        "reports/pre_live_gate/pre_live_gate_testnet_evidence_update.md",
        "reports/testnet_gate/testnet_gate_summary.json",
        "reports/micro_live_readiness/micro_live_readiness_summary.json",
        "reports/testnet_run/testnet_run_summary.json",
        "reports/shadow_decision/shadow_decision_summary.json",
        "reports/decision_engine_v2/decision_engine_v2_summary.json",
        "user_data/market_state/market_state_latest.json",
        "user_data/shadow_decision/latest_signal_snapshot.json",
        "user_data/shadow_decision/latest_shadow_snapshot.json",
    ]
    evidence_map = [evidence(path) for path in evidence_files]

    emergency_pass = bool(emergency.get("emergency_stop_check_passed") or emergency.get("status") == "PASS")
    endpoint_pass = bool(endpoint.get("passed") or testnet_run.get("endpoint_audit_passed"))
    no_real_keys = runtime["checks"].get("exchange_credentials_empty") and testnet_cfg["checks"].get("credentials_empty")
    no_risky = runtime["checks"].get("trading_mode_spot") and runtime["checks"].get("margin_mode_empty") and runtime["checks"].get("can_short_false") and testnet_cfg["checks"].get("no_fapi_dapi")
    testnet_allowed_checks = [
        matrix_row("runtime_safe", runtime["pass"], "P0", runtime, "Main runtime remains dry-run spot-only with empty credentials."),
        matrix_row("testnet_endpoint_audit_pass", endpoint_pass, "P1", endpoint or testnet_run, "Testnet endpoint audit evidence is present and passing."),
        matrix_row("testnet_config_isolated", testnet_cfg["pass"], "P0", testnet_cfg, "Testnet config is isolated from runtime and contains no credentials."),
        matrix_row("no_real_keys_on_disk", bool(no_real_keys), "P0", {"runtime": runtime, "testnet_config": testnet_cfg}, "No exchange credentials are present in runtime or testnet config."),
        matrix_row("no_futures_margin_short_leverage", bool(no_risky), "P0", {"runtime": runtime, "testnet_config": testnet_cfg}, "No futures, margin, leverage, short, fapi, or dapi is enabled."),
        matrix_row("emergency_stop_pass", emergency_pass, "P1", emergency, "Emergency stop readiness passed."),
    ]

    shadow_days = numeric(shadow, "shadow_observation_days", "observation_days", default=0)
    forward_trades = int(numeric(shadow, "forward_closed_trades", "closed_trades", default=0))
    consistency = numeric(shadow, "shadow_consistency", "consistency", default=0)
    net_filter = numeric(decision_v2, "v2_net_filter_value", "net_filter_value", "v2_all.net_filter_value", "v2.net_filter_value", default=-999999)
    prelive_blocked = read_status(PROJECT_ROOT / "reports/pre_live_gate/pre_live_gate_v3_summary.json") == "BLOCKED" or bool(prelive_v3.get("live_trading_blocked", True))
    manual_approval = (PROJECT_ROOT / "user_data/approvals/manual_micro_live_approval.md").exists()
    user_approval = (PROJECT_ROOT / "user_data/approvals/user_explicit_micro_live_approval.md").exists()
    dry_run_running = bool(dry_run_check.get("running"))
    forward_evidence_blocked = bool(dry_run_check.get("forward_evidence_blocked"))

    manual_checks = [
        matrix_row("pre_live_gate_not_blocked", not prelive_blocked, "P0", prelive_v3 or prelive, "Pre-live gate must not be BLOCKED."),
        matrix_row("shadow_observation_at_least_14_days", shadow_days >= 14, "P1", {"shadow_observation_days": shadow_days}, "Shadow observation must run at least 14 days."),
        matrix_row("forward_closed_trades_at_least_20", forward_trades >= 20, "P1", {"forward_closed_trades": forward_trades}, "Forward closed trades must be at least 20."),
        matrix_row("shadow_consistency_at_least_95_percent", consistency >= 0.95, "P1", {"shadow_consistency": consistency}, "Shadow consistency must be at least 95%."),
        matrix_row("decision_engine_net_filter_positive", net_filter > 0, "P1", {"net_filter_value": net_filter}, "Decision Engine forward net_filter_value must be positive."),
        matrix_row("slippage_stress_non_negative", False, "P1", {}, "Slippage stress evidence is not sufficient for live trading."),
        matrix_row("micro_live_readiness_not_blocked", read_status(PROJECT_ROOT / "reports/micro_live_readiness/micro_live_readiness_summary.json") != "BLOCKED", "P0", micro, "Micro-live readiness must not be BLOCKED."),
        matrix_row("manual_approval_file_exists", manual_approval, "P0", {"path": "user_data/approvals/manual_micro_live_approval.md"}, "Operator approval file must exist."),
        matrix_row("user_explicit_approval_file_exists", user_approval, "P0", {"path": "user_data/approvals/user_explicit_micro_live_approval.md"}, "User explicit approval file must exist."),
    ]

    testnet_allowed = all(row["status"] == "PASS" for row in testnet_allowed_checks)
    manual_allowed = all(row["status"] == "PASS" for row in manual_checks)
    status = "MANUAL_MICRO_LIVE_ALLOWED" if manual_allowed else ("TESTNET_ALLOWED" if testnet_allowed else "BLOCKED")
    if status == "MANUAL_MICRO_LIVE_ALLOWED" and not manual_allowed:
        status = "BLOCKED"
    auto_status = "AUTO_MICRO_LIVE_BLOCKED_BY_POLICY"

    all_rows = testnet_allowed_checks + manual_checks + [
        matrix_row("auto_micro_live_policy_block", True, "P0", {"auto_status": auto_status}, "Automatic real-money trading is policy-blocked."),
    ]
    write_csv(MATRIX, all_rows, ["check", "status", "severity", "message", "evidence"])

    summary = {
        "generated_at": utc_now(),
        "status": status,
        "auto_micro_live_status": auto_status,
        "testnet_allowed": status in ("TESTNET_ALLOWED", "MANUAL_MICRO_LIVE_ALLOWED"),
        "manual_micro_live_allowed": status == "MANUAL_MICRO_LIVE_ALLOWED",
        "auto_micro_live_allowed": False,
        "pre_live_blocked": prelive_blocked,
        "micro_live_blocked": not manual_allowed,
        "shadow_observation_days": shadow_days,
        "forward_closed_trades": forward_trades,
        "dry_run_running": dry_run_running,
        "dry_run_running_mode": dry_run_check.get("running_mode", "unknown"),
        "forward_evidence_blocked": forward_evidence_blocked,
        "forward_evidence_blocked_reason": "dry-run is not running" if forward_evidence_blocked else "",
        "decision_engine_v2_net_filter_value": net_filter,
        "evidence_files": evidence_map,
        "market_state": market_state,
        "signal_detection_status": signal_snapshot.get("signal_detection_status") or shadow_snapshot.get("signal_detection_status"),
        "blockers": [row["check"] for row in all_rows if row["status"] != "PASS"],
    }
    write_json(SUMMARY, summary)
    write_json(SYSTEM_STATE, summary)

    lines = [
        "# Gatekeeper Report",
        "",
        f"Generated: `{summary['generated_at']}`",
        f"Status: `{status}`",
        f"Auto micro-live: `{auto_status}`",
        "",
        "Gatekeeper is the authoritative project-level gate. It never enables real trading by itself.",
        "",
        "| check | status | severity | message |",
        "|---|---|---|---|",
    ]
    for row in all_rows:
        lines.append(f"| `{row['check']}` | `{row['status']}` | `{row['severity']}` | {row['message']} |")
    lines += [
        "",
        "## Decision",
        f"- Testnet allowed: `{summary['testnet_allowed']}`",
        f"- Manual micro-live allowed: `{summary['manual_micro_live_allowed']}`",
        "- Auto micro-live allowed: `False`",
        f"- Dry-run running: `{summary['dry_run_running']}`",
        f"- Dry-run mode: `{summary['dry_run_running_mode']}`",
        f"- Forward evidence blocked: `{summary['forward_evidence_blocked']}`",
        "",
        "Real small-money live trading remains forbidden unless this status explicitly becomes `MANUAL_MICRO_LIVE_ALLOWED`.",
    ]
    if forward_evidence_blocked:
        lines.insert(-2, "Forward evidence collection is blocked because dry-run is not running.")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGS.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    phase_record("gatekeeper", "PASS", f"Gatekeeper generated status {status}.", {"status": status})
    print(f"GATEKEEPER_STATUS={status}")
    return 0 if status in ("TESTNET_ALLOWED", "BLOCKED") else 2


if __name__ == "__main__":
    raise SystemExit(main())
