#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from ops_common import PROJECT_ROOT, canonical_json, git_info, load_json, redact_text, runtime_safety, sha256_text, utc_now, local_now, write_json


AUDIT_DIR = PROJECT_ROOT / "user_data/audit"
LOG = AUDIT_DIR / "audit_log.jsonl"
INDEX = AUDIT_DIR / "audit_index.json"


def previous_hash() -> str:
    if not LOG.exists():
        return "GENESIS"
    last = ""
    for line in LOG.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip():
            last = line
    if not last:
        return "GENESIS"
    try:
        return json.loads(last).get("event_hash", "GENESIS")
    except json.JSONDecodeError:
        return "BROKEN"


def build_event(args: argparse.Namespace) -> dict[str, Any]:
    git = git_info()
    prev = previous_hash()
    event = {
        "event_id": str(uuid.uuid4()),
        "run_id": args.run_id or str(uuid.uuid4()),
        "trace_id": args.trace_id or str(uuid.uuid4()),
        "timestamp_utc": utc_now(),
        "local_time": local_now(),
        "git_commit": git["commit_full"],
        "git_branch": git["branch"],
        "script_name": args.script_name,
        "command": redact_text(args.command or ""),
        "phase": args.phase,
        "event_type": args.event_type,
        "status": args.status,
        "exit_code": args.exit_code,
        "inputs_hash": args.inputs_hash or "",
        "outputs_hash": args.outputs_hash or "",
        "safety_snapshot": runtime_safety(),
        "gate_state_before": args.gate_state_before or "",
        "gate_state_after": args.gate_state_after or "",
        "redaction_applied": True,
        "previous_event_hash": prev,
        "notes": redact_text(args.notes or ""),
    }
    event["event_hash"] = sha256_text(prev + canonical_json(event))
    return event


def append_event(event: dict[str, Any]) -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
    index = load_json(INDEX, {"events": 0, "latest_event_hash": "GENESIS", "latest_event_id": ""})
    index["events"] = int(index.get("events", 0)) + 1
    index["latest_event_hash"] = event["event_hash"]
    index["latest_event_id"] = event["event_id"]
    index["updated_at"] = utc_now()
    write_json(INDEX, index)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script-name", default="manual")
    parser.add_argument("--command", default="")
    parser.add_argument("--phase", default="ops")
    parser.add_argument("--event-type", default="run")
    parser.add_argument("--status", default="PASS")
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--inputs-hash", default="")
    parser.add_argument("--outputs-hash", default="")
    parser.add_argument("--gate-state-before", default="")
    parser.add_argument("--gate-state-after", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--trace-id", default="")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    event = build_event(args)
    append_event(event)
    print(f"AUDIT_EVENT_ID={event['event_id']}")
    print(f"AUDIT_EVENT_HASH={event['event_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

