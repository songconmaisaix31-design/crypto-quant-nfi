import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_micro_live_remains_blocked():
    path = ROOT / "reports/micro_live_readiness/micro_live_readiness_summary.json"
    data = json.loads(path.read_text())
    assert data.get("status") == "BLOCKED" or data.get("micro_live_allowed") is False

