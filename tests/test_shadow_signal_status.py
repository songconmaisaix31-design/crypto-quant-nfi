import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shadow_signal_status_not_unavailable_when_snapshot_exists():
    path = ROOT / "user_data/shadow_decision/latest_signal_snapshot.json"
    if path.exists():
        data = json.loads(path.read_text())
        assert data.get("signal_detection_status") != "unavailable"

