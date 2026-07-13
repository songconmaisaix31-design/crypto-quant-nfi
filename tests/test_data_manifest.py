import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_data_manifest_generates_summary():
    proc = subprocess.run(["python3", "scripts/data_manifest.py"], cwd=ROOT, text=True, capture_output=True)
    assert proc.returncode == 0
    data = json.loads((ROOT / "reports/data_quality/data_manifest_summary.json").read_text())
    assert data["status"] == "PASS"
    assert "files_count" in data

