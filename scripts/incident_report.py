#!/usr/bin/env python3
from __future__ import annotations

import argparse
import uuid

from ops_common import PROJECT_ROOT, load_json, runtime_safety, utc_now, write_json


OUT = PROJECT_ROOT / "reports/incidents"
SEVERITIES = {
    "LIVE_TRADING_RISK": "P0",
    "SECRET_LEAK_RISK": "P0",
    "FUTURES_MARGIN_RISK": "P0",
    "MAINNET_ENDPOINT_RISK": "P0",
    "DRY_RUN_DOWN": "P2",
    "FREQ_UI_EXPOSED": "P0",
    "TESTNET_ORDER_NOT_CANCELED": "P2",
    "DATA_GAP": "P3",
    "GATEKEEPER_FAILED": "P1",
    "AUDIT_CHAIN_BROKEN": "P1",
    "UNKNOWN_ERROR": "P3",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", default="UNKNOWN_ERROR", choices=sorted(SEVERITIES))
    parser.add_argument("--detected-by", default="manual")
    parser.add_argument("--affected-file", action="append", default=[])
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    incident_id = "incident_" + utc_now().replace(":", "").replace("+", "Z") + "_" + uuid.uuid4().hex[:8]
    severity = SEVERITIES[args.type]
    gate = load_json(PROJECT_ROOT / "reports/gatekeeper/gatekeeper_summary.json", {})
    data = {
        "incident_id": incident_id,
        "incident_type": args.type,
        "severity": severity,
        "detected_by": args.detected_by,
        "timestamp": utc_now(),
        "safety_snapshot": runtime_safety(),
        "affected_files": args.affected_file,
        "recommended_action": "Force BLOCKED and investigate before continuing." if severity in {"P0", "P1"} else "Investigate and document.",
        "gatekeeper_status": gate.get("status", "MISSING"),
        "emergency_stop_required": severity == "P0",
        "resolved": False,
        "resolution_notes": "",
        "notes": args.notes,
    }
    write_json(OUT / f"{incident_id}.json", data)
    (OUT / f"{incident_id}.md").write_text(
        "# Incident Report\n\n"
        f"- Incident ID: `{incident_id}`\n"
        f"- Type: `{args.type}`\n"
        f"- Severity: `{severity}`\n"
        f"- Gatekeeper: `{data['gatekeeper_status']}`\n"
        f"- Emergency stop required: `{data['emergency_stop_required']}`\n"
        f"- Recommended action: {data['recommended_action']}\n",
        encoding="utf-8",
    )
    print(f"INCIDENT_ID={incident_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

