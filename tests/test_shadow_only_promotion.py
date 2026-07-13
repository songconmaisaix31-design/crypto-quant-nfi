from scripts.market_intelligence import candidate_decisions


def test_only_critical_failures_can_propose_shadow_block():
    snapshot = {"regime": {"regime_tags": []}, "scores": {"global_risk_appetite_score": 20, "global_liquidity_score": 50}, "confidence": {"data_confidence": 0.8}, "event_risk": {"event_risk_score": 0}}
    assert all(row["stake_multiplier"] > 0 for row in candidate_decisions(snapshot))
    snapshot["regime"]["regime_tags"] = ["critical_data_failure"]
    rows = candidate_decisions(snapshot)
    assert next(row for row in rows if row["candidate"] == "baseline_nfi")["stake_multiplier"] == 1.0
    assert all(row["stake_multiplier"] == 0 for row in rows if row["candidate"] != "baseline_nfi")
