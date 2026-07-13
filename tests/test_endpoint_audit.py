import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_endpoint_audit_script_runs_without_mainnet_pass():
    proc = subprocess.run(["python3", "scripts/testnet_endpoint_audit.py"], cwd=ROOT, text=True, capture_output=True)
    assert proc.returncode in (0, 2)
    data = json.loads((ROOT / "reports/testnet_run/testnet_endpoint_audit.json").read_text())
    assert "api.binance.com" not in json.dumps(data).lower()

