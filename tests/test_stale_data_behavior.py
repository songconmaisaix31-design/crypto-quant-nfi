from market_intelligence.data_confidence import shrink_score


def test_stale_or_unavailable_data_neutralizes_extreme_score():
    assert shrink_score(100, 0.1) == 55
    assert shrink_score(0, 0.1) == 45
