from market_intelligence.schemas import make_record, validate_record


SOURCE = {"source_id": "test", "provider": "test"}


def test_point_in_time_record_requires_available_time_after_event():
    record = make_record(SOURCE, "BTC", "metric", 1.0, event_time="2026-01-01T00:00:00+00:00", available_time="2026-01-01T00:01:00+00:00")
    assert validate_record(record) == []
    record["available_time"] = "2025-12-31T23:59:00+00:00"
    assert "available_before_event" in validate_record(record)
