import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_config_snapshot_redacts_credentials():
    proc = subprocess.run(["python3", "scripts/config_snapshot.py"], cwd=ROOT, text=True, capture_output=True)
    assert proc.returncode == 0
    latest = ROOT / "user_data/config_snapshots/latest_manifest.json"
    assert latest.exists()
    for path in (ROOT / "user_data/config_snapshots").glob("*.sanitized"):
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        assert "binance_testnet_secret=" not in text

