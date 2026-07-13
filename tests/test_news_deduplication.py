from market_intelligence.deduplication import deduplicate_news


def test_near_duplicate_news_counts_once():
    rows = [{"raw_value": "Exchange outage affects BTC withdrawals"}, {"raw_value": "Exchange outage affects BTC withdrawals!"}]
    unique, ratio = deduplicate_news(rows)
    assert len(unique) == 1
    assert ratio == 0.5
