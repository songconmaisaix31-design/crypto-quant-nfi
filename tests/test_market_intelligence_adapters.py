import json
from pathlib import Path

from market_intelligence.adapters import build_adapter


ROOT = Path(__file__).resolve().parents[1]


def test_adapters_expose_uniform_status_without_network():
    sources = json.loads((ROOT / "configs/market_intelligence_sources.yaml").read_text())["sources"]
    rules = json.loads((ROOT / "configs/source_health_rules.yaml").read_text())
    for source in sources:
        adapter = build_adapter(source, rules)
        assert callable(adapter.health_check)
        assert callable(adapter.fetch_latest)
        assert callable(adapter.fetch_historical)
        assert callable(adapter.normalize)
        assert adapter.health_check()["status"] in set(rules["statuses"])
