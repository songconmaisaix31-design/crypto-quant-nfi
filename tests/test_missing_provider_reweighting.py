from market_intelligence.scoring import weighted_available


def test_missing_provider_is_reweighted_not_zero_filled():
    score, missing = weighted_available({"a": 80, "b": None}, {"a": 0.5, "b": 0.5})
    assert score == 80
    assert missing == ["b"]
