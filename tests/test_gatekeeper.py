import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_gatekeeper_never_auto_allows():
    proc = subprocess.run(["python3", "scripts/gatekeeper.py"], cwd=ROOT, text=True, capture_output=True)
    assert proc.returncode in (0, 2)
    data = json.loads((ROOT / "reports/gatekeeper/gatekeeper_summary.json").read_text())
    assert data["status"] not in {"AUTO_MICRO_LIVE_ALLOWED", "MANUAL_MICRO_LIVE_ALLOWED"}
    assert data["auto_micro_live_status"] == "AUTO_MICRO_LIVE_BLOCKED_BY_POLICY"

