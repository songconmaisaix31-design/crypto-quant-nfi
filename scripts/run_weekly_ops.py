#!/usr/bin/env python3
from __future__ import annotations

from ops_common import PROJECT_ROOT, load_json, phase_record, read_status, utc_now, write_csv, write_json


OUT = PROJECT_ROOT / "reports/ops/weekly"
SUMMARY = OUT / "weekly_ops_summary.json"
REPORT = OUT / "weekly_ops_report.md"
METRICS = OUT / "weekly_metrics.csv"


def main() -> int:
    shadow = load_json(PROJECT_ROOT / "reports/shadow_decision/shadow_decision_summary.json", {})
    decision = load_json(PROJECT_ROOT / "reports/decision_engine_v2/decision_engine_v2_summary.json", {})
    gate = load_json(PROJECT_ROOT / "reports/gatekeeper/gatekeeper_summary.json", {})
    testnet = load_json(PROJECT_ROOT / "reports/testnet_run/testnet_run_summary.json", {})
    metrics = {
        "generated_at": utc_now(),
        "observation_days": shadow.get("shadow_observation_days") or shadow.get("observation_days") or 0,
        "forward_closed_trades": shadow.get("forward_closed_trades") or 0,
        "shadow_consistency": shadow.get("shadow_consistency") or 0,
        "net_filter_value": decision.get("net_filter_value"),
        "testnet_status": testnet.get("status"),
        "gatekeeper_status": gate.get("status"),
        "open_blockers": ";".join(gate.get("blockers", [])) if isinstance(gate.get("blockers"), list) else "",
    }
    write_json(SUMMARY, {"status": "PASS", "metrics": metrics})
    write_csv(METRICS, [metrics], list(metrics.keys()))
    REPORT.write_text(
        "# Weekly Ops Report\n\n"
        f"Gatekeeper: `{metrics['gatekeeper_status']}`\n\n"
        f"Forward closed trades: `{metrics['forward_closed_trades']}`\n\n"
        f"Decision Engine v2 net_filter_value: `{metrics['net_filter_value']}`\n\n"
        "Micro-live remains blocked unless all policy gates pass.\n",
        encoding="utf-8",
    )
    phase_record("weekly_ops", "PASS", "Weekly ops summary generated.", metrics)
    print("WEEKLY_OPS_STATUS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

