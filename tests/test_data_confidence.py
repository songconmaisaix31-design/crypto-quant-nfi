from market_intelligence.data_confidence import shrink_score


def test_low_confidence_shrinks_score_toward_neutral():
    assert shrink_score(90, 0.3) == 62
    assert shrink_score(10, 0.0) == 50
