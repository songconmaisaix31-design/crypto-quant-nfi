import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_workflow_blocks_auto_micro_live():
    proc = subprocess.run(["python3", "scripts/workflow_state.py", "--to-state", "AUTO_MICRO_LIVE_ALLOWED"], cwd=ROOT, text=True, capture_output=True)
    assert proc.returncode == 2
    assert "WORKFLOW_TRANSITION_STATUS=BLOCKED" in proc.stdout

