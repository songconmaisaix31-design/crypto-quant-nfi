#!/usr/bin/env python3
from __future__ import annotations

import json

from ops_common import PROJECT_ROOT, file_hash, git_info, load_json, phase_record, redact_value, runtime_safety, utc_now, write_json


SNAP_DIR = PROJECT_ROOT / "user_data/config_snapshots"
CONFIGS = [
    "user_data/config.runtime.json",
    "user_data/config.testnet.local.json",
    "configs/market_state_rules.yaml",
    "configs/decision_engine_rules.yaml",
    "configs/decision_engine_v2_rules.yaml",
    "configs/gatekeeper_rules.yaml",
    "configs/workflow_state.yaml",
]


def main() -> int:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    ts = utc_now().replace(":", "").replace("+", "Z")
    entries = []
    for rel in CONFIGS:
        path = PROJECT_ROOT / rel
        if not path.exists():
            continue
        if path.suffix == ".json":
            sanitized = redact_value(load_json(path, {}))
            content = json.dumps(sanitized, indent=2, ensure_ascii=False)
        else:
            content = path.read_text(encoding="utf-8", errors="ignore")
        out = SNAP_DIR / f"{ts}_{path.name}.sanitized"
        out.write_text(content + "\n", encoding="utf-8")
        entries.append({
            "timestamp": ts,
            "git_commit": git_info()["commit"],
            "config_path": rel,
            "snapshot_path": str(out.relative_to(PROJECT_ROOT)),
            "sanitized_hash": file_hash(out),
            "safety_summary": runtime_safety(),
            "gatekeeper_status": load_json(PROJECT_ROOT / "reports/gatekeeper/gatekeeper_summary.json", {}).get("status"),
        })
    write_json(SNAP_DIR / "latest_manifest.json", {"generated_at": utc_now(), "entries": entries})
    phase_record("config_snapshot", "PASS", "Sanitized config snapshots generated.", {"entries": len(entries)})
    print("CONFIG_SNAPSHOT_STATUS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

