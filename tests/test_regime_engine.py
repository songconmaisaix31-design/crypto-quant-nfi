from market_intelligence.regime import detect_regime


def test_ordinary_fear_does_not_create_critical_hard_block():
    result = detect_regime({"global_risk_appetite_score": 30, "global_liquidity_score": 60}, {"event_risk_score": 0}, {"data_confidence": 0.8})
    assert result["primary_regime"] == "risk_off"
    assert not any(tag.startswith("critical_") for tag in result["regime_tags"])
