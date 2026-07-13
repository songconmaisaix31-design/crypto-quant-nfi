import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_market_intelligence_snapshot_never_controls_orders():
    path = ROOT / "user_data/market_intelligence/scores/latest_market_intelligence.json"
    if not path.exists():
        return
    snapshot = json.loads(path.read_text())
    assert snapshot["real_trading_allowed"] is False
    assert snapshot["shadow_only"] is True
    assert all(row["controls_orders"] is False for row in snapshot["candidate_decisions"])
