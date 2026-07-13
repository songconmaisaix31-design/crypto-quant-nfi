#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from ops_common import PROJECT_ROOT, load_json, phase_record, read_status, utc_now, write_json


STATE_PATH = PROJECT_ROOT / "user_data/workflow/workflow_state.json"
REPORT = PROJECT_ROOT / "reports/workflow/workflow_state_report.md"
HISTORY = PROJECT_ROOT / "reports/workflow/workflow_state_history.csv"
ALLOWED = {
    "RESEARCH_READY": {"DRY_RUN_ACTIVE"},
    "DRY_RUN_ACTIVE": {"SHADOW_OBSERVING"},
    "SHADOW_OBSERVING": {"TESTNET_READY"},
    "TESTNET_READY": {"TESTNET_VALIDATED"},
    "TESTNET_VALIDATED": {"MANUAL_MICRO_LIVE_PENDING_APPROVAL"},
}


def infer_state() -> str:
    gate = read_status(PROJECT_ROOT / "reports/gatekeeper/gatekeeper_summary.json")
    testnet_run = load_json(PROJECT_ROOT / "reports/testnet_run/testnet_run_summary.json", {})
    micro = read_status(PROJECT_ROOT / "reports/micro_live_readiness/micro_live_readiness_summary.json")
    if micro == "BLOCKED":
        if testnet_run.get("order_lifecycle_verified"):
            return "TESTNET_VALIDATED"
        if gate == "TESTNET_ALLOWED":
            return "TESTNET_READY"
        return "SHADOW_OBSERVING"
    return "SHADOW_OBSERVING"


def append_history(row: dict[str, str]) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    exists = HISTORY.exists()
    with HISTORY.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "from_state", "to_state", "reason", "evidence_files", "gatekeeper_status", "operator", "audit_event_id"])
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--to-state", default="")
    parser.add_argument("--reason", default="automatic evidence inference")
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--operator", default="codex")
    parser.add_argument("--audit-event-id", default="")
    args = parser.parse_args()

    current = load_json(STATE_PATH, {})
    from_state = current.get("state") or "RESEARCH_READY"
    target = args.to_state or infer_state()
    evidence_files = args.evidence or ["reports/gatekeeper/gatekeeper_summary.json", "reports/testnet_run/testnet_run_summary.json"]
    evidence_ok = all((PROJECT_ROOT / p).exists() for p in evidence_files)
    allowed = target == from_state or target in ALLOWED.get(from_state, set()) or (from_state == "RESEARCH_READY" and target in {"SHADOW_OBSERVING", "TESTNET_READY", "TESTNET_VALIDATED"})
    if target == "AUTO_MICRO_LIVE_ALLOWED":
        allowed = False
    if target == "MANUAL_MICRO_LIVE_ALLOWED":
        allowed = False
    status = "PASS" if allowed and evidence_ok else "BLOCKED"
    final_state = target if status == "PASS" else from_state
    gatekeeper_status = read_status(PROJECT_ROOT / "reports/gatekeeper/gatekeeper_summary.json")
    state = {
        "generated_at": utc_now(),
        "state": final_state,
        "requested_state": target,
        "transition_status": status,
        "from_state": from_state,
        "reason": args.reason,
        "evidence_files": evidence_files,
        "gatekeeper_status": gatekeeper_status,
        "operator": args.operator,
        "audit_event_id": args.audit_event_id,
    }
    write_json(STATE_PATH, state)
    append_history({
        "timestamp": state["generated_at"],
        "from_state": from_state,
        "to_state": final_state,
        "reason": args.reason,
        "evidence_files": ";".join(evidence_files),
        "gatekeeper_status": gatekeeper_status,
        "operator": args.operator,
        "audit_event_id": args.audit_event_id,
    })
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        "# Workflow State Report\n\n"
        f"State: `{final_state}`\n\n"
        f"Transition status: `{status}`\n\n"
        f"Gatekeeper: `{gatekeeper_status}`\n\n"
        "Manual and auto micro-live states remain blocked unless explicit gate evidence exists.\n",
        encoding="utf-8",
    )
    phase_record("workflow_state", status, f"Workflow state is {final_state}.", {"state": final_state, "requested_state": target})
    print(f"WORKFLOW_STATE={final_state}")
    print(f"WORKFLOW_TRANSITION_STATUS={status}")
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

