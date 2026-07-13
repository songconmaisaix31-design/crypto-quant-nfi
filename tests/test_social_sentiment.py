from market_intelligence.scoring import social_scores


def test_crowding_is_separate_from_directional_sentiment():
    result = social_scores(80, 20, 10, 50, 100, [10, 20, 30], 0.8, 0.9, 0.1, 0.05)
    assert result["sentiment_balance"] > 0
    assert "social_crowding_score" in result
    assert result["social_contrarian_score"] <= 0
