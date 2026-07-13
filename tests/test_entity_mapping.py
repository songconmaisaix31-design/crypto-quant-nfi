from market_intelligence.entity_mapping import normalize_asset


def test_entity_mapping_rejects_stable_and_leveraged_tokens():
    assert normalize_asset("BTC/USDT")[0] == "BTC"
    assert "stablecoin" in normalize_asset("USDC/USDT")[1]
    assert "leveraged_token" in normalize_asset("BTCUP/USDT")[1]
