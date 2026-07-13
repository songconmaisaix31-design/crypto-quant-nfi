#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dry_run_status import dry_run_status
from ops_common import PROJECT_ROOT, git_info, load_json, phase_record, read_status, run_cmd, runtime_safety, utc_now, write_json


OUT = PROJECT_ROOT / "reports/forward_evidence"


def command_result(name: str, cmd: list[str], timeout: int = 240) -> dict[str, Any]:
    result = run_cmd(cmd, timeout=timeout)
    result["name"] = name
    return result


def precheck_commands() -> list[dict[str, Any]]:
    return [
        command_result("status_native", ["bash", "scripts/status-native.sh"]),
        command_result("ensure_dry_run_running", ["bash", "scripts/ensure-dry-run-running.sh"]),
        command_result("gatekeeper", ["bash", "scripts/gatekeeper.sh"]),
        command_result("pre_live_gate", ["bash", "scripts/pre-live-gate.sh"]),
        command_result("micro_live_readiness", ["bash", "scripts/micro-live-readiness.sh"]),
        command_result("emergency_stop_check", ["bash", "scripts/emergency-stop-check.sh"]),
        command_result("secret_scan", ["bash", "scripts/secret-scan.sh"]),
        command_result("audit_verify", ["bash", "scripts/audit-verify.sh"]),
    ]


def postcheck_commands() -> list[dict[str, Any]]:
    return [
        command_result("status_native", ["bash", "scripts/status-native.sh"]),
        command_result("ensure_dry_run_running", ["bash", "scripts/ensure-dry-run-running.sh"]),
        command_result("run_daily_ops", ["bash", "scripts/run-daily-ops.sh"], timeout=420),
        command_result("gatekeeper", ["bash", "scripts/gatekeeper.sh"]),
        command_result("shadow_signal_check", ["bash", "scripts/shadow-signal-check.sh"], timeout=420),
        command_result("shadow_decision_journal", ["bash", "scripts/shadow-decision-journal.sh"], timeout=300),
        command_result("shadow_decision_daily_report", ["bash", "scripts/shadow-decision-daily-report.sh"], timeout=300),
    ]


def status_bundle() -> dict[str, Any]:
    dry = dry_run_status()
    gate = load_json(PROJECT_ROOT / "reports/gatekeeper/gatekeeper_summary.json", {})
    prelive = load_json(PROJECT_ROOT / "reports/pre_live_gate/pre_live_gate_summary.json", {})
    micro = load_json(PROJECT_ROOT / "reports/micro_live_readiness/micro_live_readiness_summary.json", {})
    emergency = load_json(PROJECT_ROOT / "reports/micro_live_readiness/emergency_stop_check_summary.json", {})
    audit = load_json(PROJECT_ROOT / "reports/audit/audit_summary.json", {})
    audit_verify = PROJECT_ROOT / "reports/audit/audit_verification_report.md"
    secret_findings = PROJECT_ROOT / "reports/audit/secret_scan_findings.csv"
    secret_findings_count = 0
    if secret_findings.exists():
        secret_findings_count = max(0, len(secret_findings.read_text(encoding="utf-8", errors="ignore").splitlines()) - 1)
    shadow = load_json(PROJECT_ROOT / "reports/shadow_decision/shadow_decision_summary.json", {})
    daily = load_json(PROJECT_ROOT / "reports/ops/daily/daily_ops_summary.json", {})
    return {
        "generated_at": utc_now(),
        "git": git_info(),
        "runtime_safety": runtime_safety(),
        "dry_run": {
            "status": dry["status"],
            "running": dry["running"],
            "running_mode": dry["running_mode"],
            "forward_evidence_blocked": dry["forward_evidence_blocked"],
            "systemd_system_active": dry["systemd_system"].get("active"),
            "systemd_user_active": dry["systemd_user"].get("active"),
            "freqtrade_trade_processes": len(dry["freqtrade_trade_processes"]),
            "hidden_windows_wsl_carrier_detected": dry["hidden_windows_wsl_carrier"]["detected"],
            "api_health_reachable": dry["api_health"].get("reachable"),
        },
        "gatekeeper_status": gate.get("status", "MISSING"),
        "testnet_allowed": bool(gate.get("testnet_allowed")),
        "pre_live_blocked": bool(prelive.get("live_trading_blocked", True)),
        "micro_live_status": micro.get("status", "BLOCKED"),
        "manual_micro_live_allowed": bool(micro.get("manual_micro_live_allowed", False)),
        "emergency_stop_pass": bool(emergency.get("emergency_stop_check_passed") or emergency.get("status") == "PASS"),
        "audit_verify_pass": "Status: `PASS`" in audit_verify.read_text(encoding="utf-8", errors="ignore") if audit_verify.exists() else audit.get("status") == "PASS",
        "secret_scan_status": "PASS" if secret_findings.exists() and secret_findings_count == 0 else "REVIEW",
        "secret_scan_findings_count": secret_findings_count,
        "daily_ops_status": daily.get("status", "MISSING"),
        "signal_detection_status": shadow.get("signal_detection_status", "MISSING"),
        "confirmed_signal_count": int(shadow.get("confirmed_signal_count") or 0),
        "new_signal_since_last_snapshot": int(shadow.get("new_signal_since_last_snapshot") or 0),
        "new_trade_since_last_snapshot": int(shadow.get("new_trade_since_last_snapshot") or 0),
        "recent_closed_trades_count": int(shadow.get("recent_closed_trades_count") or 0),
        "shadow_observation_days": float(shadow.get("observation_days") or shadow.get("shadow_observation_days") or 0),
        "forward_closed_trades": int(shadow.get("forward_closed_trades") or shadow.get("recent_closed_trades_count") or 0),
        "shadow_consistency": shadow.get("shadow_consistency", shadow.get("consistency_status", "")),
    }


def blocked_reasons(bundle: dict[str, Any]) -> list[str]:
    reasons = []
    if not bundle["runtime_safety"]["pass"]:
        reasons.append("runtime safety check failed")
    if not bundle["emergency_stop_pass"]:
        reasons.append("emergency stop check failed")
    if not bundle["audit_verify_pass"]:
        reasons.append("audit verify failed")
    if bundle["secret_scan_status"] not in ("PASS", "MISSING"):
        reasons.append("secret scan is not PASS")
    return reasons


def write_precheck(results: list[dict[str, Any]]) -> dict[str, Any]:
    bundle = status_bundle()
    reasons = blocked_reasons(bundle)
    summary = {
        **bundle,
        "status": "BLOCKED" if reasons else "PASS",
        "blocked_reasons": reasons,
        "commands": results,
        "real_trading_allowed": False,
        "micro_live_allowed": False,
    }
    write_json(OUT / "activation_precheck.json", summary)
    lines = [
        "# Forward Evidence Activation Precheck",
        "",
        f"Status: `{summary['status']}`",
        f"Dry-run running before start: `{bundle['dry_run']['running']}`",
        f"Gatekeeper: `{bundle['gatekeeper_status']}`",
        f"Pre-live blocked: `{bundle['pre_live_blocked']}`",
        f"Micro-live status: `{bundle['micro_live_status']}`",
        f"Emergency Stop PASS: `{bundle['emergency_stop_pass']}`",
        f"Audit Verify PASS: `{bundle['audit_verify_pass']}`",
        f"Secret Scan: `{bundle['secret_scan_status']}`",
        "",
        "Real-money trading remains forbidden.",
    ]
    if reasons:
        lines += ["", "## Blockers", *[f"- {reason}" for reason in reasons]]
    (OUT / "activation_precheck.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    phase_record("forward_evidence_precheck", summary["status"], "Forward evidence precheck generated.", {"blocked_reasons": reasons})
    return summary


def write_start_attempt(result: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    status = "PASS" if after["running"] else "BLOCKED"
    summary = {
        "generated_at": utc_now(),
        "status": status,
        "command": result,
        "before": before,
        "after": {
            "status": after["status"],
            "running": after["running"],
            "running_mode": after["running_mode"],
            "forward_evidence_blocked": after["forward_evidence_blocked"],
        },
        "real_trading_allowed": False,
        "micro_live_allowed": False,
    }
    write_json(OUT / "dry_run_start_attempt.json", summary)
    (OUT / "dry_run_start_logs.txt").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    lines = [
        "# Dry-run Start Attempt",
        "",
        f"Status: `{status}`",
        f"Start exit code: `{result['exit_code']}`",
        f"Dry-run running after start: `{after['running']}`",
        f"Dry-run mode after start: `{after['running_mode']}`",
        f"Forward evidence blocked: `{after['forward_evidence_blocked']}`",
        "",
        "The start path is restricted to the existing dry-run runtime. Real-money trading remains forbidden.",
    ]
    if not after["running"]:
        lines += ["", "Forward evidence collection remains blocked because dry-run is not running."]
    (OUT / "dry_run_start_attempt.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    phase_record("forward_evidence_start", status, "Dry-run start attempt recorded.", {"running": after["running"]})
    return summary


def write_postcheck(results: list[dict[str, Any]]) -> dict[str, Any]:
    bundle = status_bundle()
    status = "PASS" if bundle["dry_run"]["running"] else "BLOCKED"
    summary = {
        **bundle,
        "status": status,
        "commands": results,
        "real_trading_allowed": False,
        "micro_live_allowed": False,
    }
    write_json(OUT / "activation_postcheck.json", summary)
    lines = [
        "# Forward Evidence Activation Postcheck",
        "",
        f"Status: `{status}`",
        f"Dry-run running: `{bundle['dry_run']['running']}`",
        f"Dry-run mode: `{bundle['dry_run']['running_mode']}`",
        f"FreqUI/API reachable: `{bundle['dry_run']['api_health_reachable']}`",
        f"Forward evidence blocked: `{bundle['dry_run']['forward_evidence_blocked']}`",
        f"Daily Ops: `{bundle['daily_ops_status']}`",
        f"Gatekeeper: `{bundle['gatekeeper_status']}`",
        f"Pre-live blocked: `{bundle['pre_live_blocked']}`",
        f"Micro-live status: `{bundle['micro_live_status']}`",
        f"Signal detection: `{bundle['signal_detection_status']}`",
        f"New signal since last snapshot: `{bundle['new_signal_since_last_snapshot']}`",
        f"New trade since last snapshot: `{bundle['new_trade_since_last_snapshot']}`",
        f"Recent closed trades: `{bundle['recent_closed_trades_count']}`",
    ]
    if not bundle["dry_run"]["running"]:
        lines += ["", "Forward evidence collection remains blocked because dry-run is not running."]
    (OUT / "activation_postcheck.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    phase_record("forward_evidence_postcheck", status, "Forward evidence postcheck generated.", {"dry_run_running": bundle["dry_run"]["running"]})
    return summary


def write_next_steps() -> None:
    bundle = status_bundle()
    if bundle["dry_run"]["running"]:
        first_action = "每天运行 `bash scripts/run-daily-ops.sh`、`bash scripts/gatekeeper.sh`、`bash scripts/audit-verify.sh`、`bash scripts/secret-scan.sh`，继续累计 14-28 天 forward evidence。"
    else:
        first_action = "先运行 `bash scripts/ensure-dry-run-running.sh --start`，再运行 `bash scripts/status-native.sh` 确认 dry-run 已启动。"
    lines = [
        "# Next Steps When User Wakes Up",
        "",
        f"1. 当前 dry-run 是否运行：`{bundle['dry_run']['running']}`",
        f"2. 当前 Gatekeeper 状态：`{bundle['gatekeeper_status']}`",
        f"3. 当前 Micro-live 是否 BLOCKED：`{not bundle['manual_micro_live_allowed']}`",
        f"4. 今日新 signal：`{bundle['new_signal_since_last_snapshot']}`",
        f"5. 今日新 dry-run trade：`{bundle['new_trade_since_last_snapshot']}`",
        f"6. 今日 closed trade：`{bundle['recent_closed_trades_count']}`",
        f"7. Daily Ops 是否 PASS：`{bundle['daily_ops_status'] == 'PASS'}`",
        f"8. Audit Verify 是否 PASS：`{bundle['audit_verify_pass']}`",
        f"9. Secret Scan 是否 PASS：`{bundle['secret_scan_status'] == 'PASS'}`",
        f"10. 醒来后第一件事：{first_action}",
        "11. 真实小金额实盘仍不允许。",
        "12. 下一次评估 micro-live 的硬门槛：shadow observation >= 14 天、forward closed trades >= 20、shadow consistency >= 95%、forward net_filter_value > 0、slippage stress 后非负、Gatekeeper 输出 MANUAL_MICRO_LIVE_ALLOWED。",
    ]
    (OUT / "NEXT_STEPS_WHEN_USER_WAKES_UP.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_final() -> dict[str, Any]:
    bundle = status_bundle()
    pre = load_json(OUT / "activation_precheck.json", {})
    post = load_json(OUT / "activation_postcheck.json", {})
    watch = load_json(OUT / "watch_summary.json", {})
    summary = {
        **bundle,
        "status": "PASS" if bundle["dry_run"]["running"] else "BLOCKED",
        "precheck_status": pre.get("status", "MISSING"),
        "postcheck_status": post.get("status", "MISSING"),
        "watch_status": watch.get("status", "MISSING"),
        "allowed_now": ["dry-run", "shadow observation", "testnet practice"],
        "forbidden_now": ["real-money live trading", "auto live trading", "futures", "margin", "leverage", "short"],
        "real_trading_allowed": False,
        "micro_live_allowed": False,
    }
    write_json(OUT / "final_forward_evidence_activation_summary.json", summary)
    lines = [
        "# Final Forward Evidence Activation Report",
        "",
        f"Status: `{summary['status']}`",
        f"Dry-run running: `{bundle['dry_run']['running']}`",
        f"Dry-run mode: `{bundle['dry_run']['running_mode']}`",
        f"Forward evidence blocked: `{bundle['dry_run']['forward_evidence_blocked']}`",
        f"Daily Ops: `{bundle['daily_ops_status']}`",
        f"Gatekeeper: `{bundle['gatekeeper_status']}`",
        f"Pre-live blocked: `{bundle['pre_live_blocked']}`",
        f"Micro-live status: `{bundle['micro_live_status']}`",
        f"Signal detection: `{bundle['signal_detection_status']}`",
        f"New signal today: `{bundle['new_signal_since_last_snapshot']}`",
        f"New dry-run trade today: `{bundle['new_trade_since_last_snapshot']}`",
        f"Closed trade today: `{bundle['recent_closed_trades_count']}`",
        f"Shadow observation days: `{bundle['shadow_observation_days']}`",
        f"Forward closed trades: `{bundle['forward_closed_trades']}`",
        f"Audit Verify PASS: `{bundle['audit_verify_pass']}`",
        f"Secret Scan: `{bundle['secret_scan_status']}`",
        "",
        "Allowed now: dry-run, shadow observation, and testnet practice only.",
        "",
        "Forbidden now: real-money live trading, automatic real-money trading, futures, margin, leverage, and shorting.",
        "",
        "Only a future Gatekeeper status of `MANUAL_MICRO_LIVE_ALLOWED` permits discussion of manual micro-live.",
        "",
        "This is not investment advice. Real trading can lose all capital.",
    ]
    if not bundle["dry_run"]["running"]:
        lines += ["", "Forward evidence collection remains blocked because dry-run is not running."]
    (OUT / "final_forward_evidence_activation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    phase_record("forward_evidence_final", summary["status"], "Final forward evidence activation report generated.", {"dry_run_running": bundle["dry_run"]["running"]})
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["precheck", "start-report", "postcheck", "next-steps", "final"])
    parser.add_argument("--start-result", type=Path)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    if args.action == "precheck":
        summary = write_precheck(precheck_commands())
        print(f"FORWARD_EVIDENCE_PRECHECK={summary['status']}")
        return 0 if summary["status"] != "BLOCKED" else 2
    if args.action == "start-report":
        result = load_json(args.start_result or OUT / "dry_run_start_command.json", {})
        before = load_json(OUT / "activation_precheck.json", {}).get("dry_run", {})
        after = dry_run_status()
        summary = write_start_attempt(result, before, after)
        print(f"FORWARD_EVIDENCE_START={summary['status']}")
        return 0 if summary["status"] == "PASS" else 2
    if args.action == "postcheck":
        summary = write_postcheck(postcheck_commands())
        print(f"FORWARD_EVIDENCE_POSTCHECK={summary['status']}")
        return 0 if summary["status"] != "BLOCKED" else 2
    if args.action == "next-steps":
        write_next_steps()
        print("FORWARD_EVIDENCE_NEXT_STEPS=PASS")
        return 0
    summary = write_final()
    print(f"FORWARD_EVIDENCE_FINAL={summary['status']}")
    return 0 if summary["status"] != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
