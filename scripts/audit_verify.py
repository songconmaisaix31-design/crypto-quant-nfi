#!/usr/bin/env python3
from __future__ import annotations

import json

from ops_common import PROJECT_ROOT, canonical_json, phase_record, sha256_text, utc_now, write_json


LOG = PROJECT_ROOT / "user_data/audit/audit_log.jsonl"
OUT = PROJECT_ROOT / "reports/audit"
SUMMARY = OUT / "audit_summary.json"
REPORT = OUT / "audit_verification_report.md"
LOGS = OUT / "audit_logs.txt"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    events = []
    errors = []
    prev = "GENESIS"
    if LOG.exists():
        for line_no, line in enumerate(LOG.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_no}: invalid json {exc}")
                continue
            expected_prev = event.get("previous_event_hash")
            if expected_prev != prev:
                errors.append(f"line {line_no}: previous hash mismatch")
            expected_event = dict(event)
            event_hash = expected_event.pop("event_hash", "")
            recomputed = sha256_text(str(expected_prev) + canonical_json(expected_event))
            if event_hash != recomputed:
                errors.append(f"line {line_no}: event hash mismatch")
            prev = event_hash
            events.append(event)
    summary = {
        "generated_at": utc_now(),
        "status": "PASS" if not errors else "BLOCKED",
        "audit_log_exists": LOG.exists(),
        "events_count": len(events),
        "latest_event_hash": prev,
        "errors": errors,
    }
    write_json(SUMMARY, summary)
    write_json(OUT / "audit_report.md.json", summary)
    lines = [
        "# Audit Verification Report",
        "",
        f"Generated: `{summary['generated_at']}`",
        f"Status: `{summary['status']}`",
        f"Audit log exists: `{summary['audit_log_exists']}`",
        f"Events: `{summary['events_count']}`",
        "",
    ]
    if errors:
        lines += ["## Errors", *[f"- {error}" for error in errors]]
    else:
        lines.append("Hash chain verification passed.")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGS.write_text("\n".join(errors) + "\n", encoding="utf-8")
    phase_record("audit_verify", summary["status"], f"Audit verification {summary['status']}.", {"events": len(events), "errors": errors})
    print(f"AUDIT_VERIFY_STATUS={summary['status']}")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

