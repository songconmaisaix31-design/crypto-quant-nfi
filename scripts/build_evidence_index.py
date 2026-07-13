#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from ops_common import PROJECT_ROOT, git_info, load_json, phase_record, read_status, utc_now, write_csv, write_json


OUT_MD = PROJECT_ROOT / "reports/EVIDENCE_INDEX.md"
OUT_JSON = PROJECT_ROOT / "reports/evidence_index.json"
OUT_CSV = PROJECT_ROOT / "reports/evidence_matrix.csv"
PROJECT_STATUS = PROJECT_ROOT / "reports/PROJECT_STATUS.md"

MODULES = {
    "no_trade": ["reports/no_trade_report.md", "reports/no_trade_summary.json"],
    "sample_validation": ["reports/sample_validation/sample_validation_report.md", "reports/sample_validation/sample_validation_summary.json"],
    "strategy_explain": ["reports/strategy_explain/strategy_explain_report.md", "reports/strategy_explain/strategy_explain_summary.json"],
    "market_state": ["reports/market_state/market_state_report.md", "reports/market_state/market_state_summary.json"],
    "decision_engine_v1": ["reports/decision_engine/decision_engine_report.md", "reports/decision_engine/decision_engine_summary.json"],
    "decision_engine_v2": ["reports/decision_engine_v2/decision_engine_v2_report.md", "reports/decision_engine_v2/decision_engine_v2_summary.json"],
    "shadow_decision": ["reports/shadow_decision/shadow_decision_daily_report.md", "reports/shadow_decision/shadow_decision_summary.json"],
    "signal_check": ["reports/shadow_decision/shadow_signal_check_report.md"],
    "pre_live_gate": ["reports/pre_live_gate/pre_live_gate_report.md", "reports/pre_live_gate/pre_live_gate_summary.json"],
    "testnet_gate": ["reports/testnet_gate/testnet_gate_report.md", "reports/testnet_gate/testnet_gate_summary.json"],
    "micro_live_readiness": ["reports/micro_live_readiness/micro_live_readiness_report.md", "reports/micro_live_readiness/micro_live_readiness_summary.json"],
    "emergency_stop": ["reports/micro_live_readiness/emergency_stop_check_report.md", "reports/micro_live_readiness/emergency_stop_check_summary.json"],
    "testnet_run": ["reports/testnet_run/testnet_run_report.md", "reports/testnet_run/testnet_run_summary.json"],
    "gatekeeper": ["reports/gatekeeper/gatekeeper_report.md", "reports/gatekeeper/gatekeeper_summary.json"],
    "audit": ["reports/audit/audit_report.md", "reports/audit/audit_summary.json"],
    "daily_ops": ["reports/ops/daily/daily_ops_report.md", "reports/ops/daily/daily_ops_summary.json"],
    "data_manifest": ["reports/data_quality/data_manifest_report.md", "reports/data_quality/data_manifest_summary.json"],
    "forward_evidence": ["reports/forward_evidence/final_forward_evidence_activation_report.md", "reports/forward_evidence/final_forward_evidence_activation_summary.json"],
    "community_intelligence": ["reports/community_intelligence/community_intel_report.md", "reports/community_intelligence/community_intel_summary.json"],
    "hypotheses": ["reports/hypotheses/hypothesis_registry.md", "reports/hypotheses/hypothesis_summary.json"],
    "optimization_experiments": ["reports/optimization_experiments/optimization_experiment_index.json"],
    "walkforward": ["reports/optimization/walkforward_report.md", "reports/optimization/walkforward_summary.json"],
    "anti_overfit": ["reports/optimization/anti_overfit_report.md", "reports/optimization/anti_overfit_summary.json"],
    "stable_profit_score": ["reports/optimization/stable_profit_score_report.md", "reports/optimization/stable_profit_score_summary.json"],
    "shadow_promotion": ["reports/shadow_promotion/shadow_promotion_report.md", "reports/shadow_promotion/shadow_promotion_summary.json"],
    "community_weekly": ["reports/community_intelligence/community_weekly_report.md", "reports/community_intelligence/community_weekly_summary.json"],
    "optimization_dashboard": ["reports/optimization/OPTIMIZATION_DASHBOARD.md", "reports/optimization/optimization_dashboard.json"],
    "hyperopt_research": ["reports/hyperopt_research/hyperopt_research_plan.md", "reports/hyperopt_research/hyperopt_research_summary.json"],
    "stable_profit_loop": [
        "reports/stable_profit_loop/stable_profit_loop_report.md",
        "reports/stable_profit_loop/stable_profit_loop_summary.json",
        "reports/stable_profit_loop/version_status.md",
        "reports/stable_profit_loop/v11_next_step_report.md",
        "reports/stable_profit_loop/v11_next_step_summary.json",
        "reports/forward_evidence/v11_dry_run_activation_report.md",
        "reports/forward_evidence/v11_dry_run_activation_summary.json",
    ],
    "market_intelligence": [
        "reports/market_intelligence/final_market_intelligence_report.md",
        "reports/market_intelligence/final_market_intelligence_summary.json",
        "reports/market_intelligence/source_health_summary.json",
        "reports/market_intelligence/latest_market_intelligence.json",
    ],
    "evidence_throughput": [
        "reports/CONTEXT.md",
        "reports/evidence_throughput/evidence_throughput_report.md",
        "reports/evidence_throughput/evidence_throughput_summary.json",
        "reports/evidence_throughput/evidence_throughput_history.csv",
    ],
}


def status_for(files: list[str]) -> str:
    for rel in files:
        if rel.endswith(".json"):
            status = read_status(PROJECT_ROOT / rel)
            if status != "MISSING":
                return status
    return "PRESENT" if any((PROJECT_ROOT / rel).exists() for rel in files) else "MISSING"


def main() -> int:
    rows = []
    git = git_info()
    for idx, (module, files) in enumerate(MODULES.items(), start=1):
        existing = [rel for rel in files if (PROJECT_ROOT / rel).exists()]
        rows.append({
            "evidence_id": f"EV-{idx:03d}",
            "title": module.replace("_", " ").title(),
            "file_path": ";".join(existing),
            "module": module,
            "status": status_for(files),
            "generated_at": utc_now(),
            "git_commit": git["commit"],
            "input_files": "",
            "output_files": ";".join(files),
            "supports_gate": module in {"pre_live_gate", "testnet_gate", "micro_live_readiness", "emergency_stop", "testnet_run", "gatekeeper"},
            "limitations": "Missing evidence" if not existing else "",
            "next_required_evidence": "Run module script" if not existing else "",
        })
    write_json(OUT_JSON, {"generated_at": utc_now(), "evidence": rows})
    write_csv(OUT_CSV, rows, ["evidence_id", "title", "file_path", "module", "status", "generated_at", "git_commit", "input_files", "output_files", "supports_gate", "limitations", "next_required_evidence"])
    lines = ["# Evidence Index", "", "| id | module | status | files |", "|---|---|---|---|"]
    for row in rows:
        lines.append(f"| `{row['evidence_id']}` | `{row['module']}` | `{row['status']}` | `{row['file_path']}` |")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    gate = load_json(PROJECT_ROOT / "reports/gatekeeper/gatekeeper_summary.json", {})
    micro = load_json(PROJECT_ROOT / "reports/micro_live_readiness/micro_live_readiness_summary.json", {})
    testnet = load_json(PROJECT_ROOT / "reports/testnet_run/testnet_run_summary.json", {})
    daily = load_json(PROJECT_ROOT / "reports/ops/daily/daily_ops_summary.json", {})
    shadow = load_json(PROJECT_ROOT / "reports/shadow_decision/shadow_decision_summary.json", {})
    stable_loop = load_json(PROJECT_ROOT / "reports/stable_profit_loop/stable_profit_loop_summary.json", {})
    dashboard = load_json(PROJECT_ROOT / "reports/optimization/optimization_dashboard.json", {})
    market_intelligence = load_json(PROJECT_ROOT / "reports/market_intelligence/final_market_intelligence_summary.json", {})
    forward_blocked = daily.get("forward_evidence_blocked", gate.get("forward_evidence_blocked", False))
    next_step = (
        "Start dry-run with `bash scripts/ensure-dry-run-running.sh --start`, then rerun daily ops."
        if forward_blocked
        else "Keep running daily ops, gatekeeper, audit verify, and secret scan during the 14-28 day observation period."
    )
    PROJECT_STATUS.write_text(
        "# Project Status\n\n"
        f"- Gatekeeper: `{gate.get('status', 'MISSING')}`\n"
        f"- Testnet allowed: `{gate.get('testnet_allowed', False)}`\n"
        f"- Micro-live allowed: `{gate.get('manual_micro_live_allowed', False)}`\n"
        f"- Testnet run: `{testnet.get('status', 'MISSING')}`\n"
        f"- Micro-live readiness: `{micro.get('status', 'BLOCKED')}`\n\n"
        f"- Dry-run running: `{daily.get('dry_run_running', gate.get('dry_run_running', False))}`\n"
        f"- Dry-run mode: `{daily.get('dry_run_running_mode', gate.get('dry_run_running_mode', 'unknown'))}`\n"
        f"- Forward evidence blocked: `{forward_blocked}`\n"
        f"- Shadow observation days: `{shadow.get('observation_days', gate.get('shadow_observation_days', 0))}`\n"
        f"- Forward closed trades: `{shadow.get('forward_closed_trades', gate.get('forward_closed_trades', 0))}`\n"
        f"- Shadow consistency: `{shadow.get('shadow_consistency', shadow.get('consistency_status', 'unknown'))}`\n\n"
        "## Stable Profit Evidence Loop\n\n"
        f"- Loop status: `{stable_loop.get('status', 'MISSING')}`\n"
        f"- Top research direction: `{stable_loop.get('best_direction', 'MISSING')}`\n"
        f"- Best candidate: `{dashboard.get('best_candidate', {}).get('candidate_id', 'MISSING')}`\n"
        f"- Stable profit score: `{dashboard.get('stable_profit_score', 0)}`\n"
        f"- Open blockers: `{len(dashboard.get('open_blockers', []))}`\n\n"
        "## Multi-Source Market Intelligence\n\n"
        f"- Providers available: `{len(market_intelligence.get('providers_available', []))}`\n"
        f"- Data confidence: `{market_intelligence.get('data_confidence', 'MISSING')}`\n"
        f"- Market regime: `{market_intelligence.get('market_regime', 'MISSING')}`\n"
        f"- Candidate ready for shadow: `{market_intelligence.get('candidate_ready_for_shadow', False)}`\n"
        "- External intelligence controls real orders: `False`\n\n"
        "Allowed now: dry-run, shadow observation, and testnet practice only.\n\n"
        "Forbidden now: real-money live trading, futures, margin, leverage, shorting, public FreqUI, key persistence.\n\n"
        f"Next step: {next_step}\n\n"
        "Run daily ops with `bash scripts/run-daily-ops.sh`.\n",
        encoding="utf-8",
    )
    phase_record("evidence_index", "PASS", "Evidence index generated.", {"entries": len(rows)})
    print("EVIDENCE_INDEX_STATUS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
