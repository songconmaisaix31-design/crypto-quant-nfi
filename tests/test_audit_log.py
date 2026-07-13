import json
import subprocess
from pathlib import Path

from scripts.ops_common import canonical_json, sha256_text


ROOT = Path(__file__).resolve().parents[1]


def test_audit_hash_chain_can_verify():
    proc = subprocess.run(
        ["python3", "scripts/audit-log.py", "--script-name", "pytest", "--command", "pytest", "--phase", "test", "--status", "PASS"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0
    verify = subprocess.run(["python3", "scripts/audit_verify.py"], cwd=ROOT, text=True, capture_output=True)
    assert verify.returncode == 0
    last = [line for line in (ROOT / "user_data/audit/audit_log.jsonl").read_text().splitlines() if line][-1]
    event = json.loads(last)
    event_hash = event.pop("event_hash")
    assert sha256_text(event["previous_event_hash"] + canonical_json(event)) == event_hash

