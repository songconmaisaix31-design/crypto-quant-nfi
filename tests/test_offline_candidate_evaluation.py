from scripts.offline_candidate_evaluation import candidate_multiplier, evaluate_candidate


def signal_row(profit: float) -> dict:
    return {
        "baseline_profit": profit,
        "primary_regime": "fear",
        "regime_tags": "fear risk_off",
        "pair_quality_score": 30.0,
        "risk_score": 75.0,
        "market_sentiment_score": 25.0,
        "v2_stake_multiplier": 0.0,
        "decision_reason": "hard_pair_quality:risk_off",
        "pair_atr_percent": 10.0,
        "btc_trend_score": 20.0,
        "market_breadth_score": 25.0,
    }


def test_candidate_decision_does_not_use_realized_profit():
    winner = signal_row(10.0)
    loser = signal_row(-10.0)
    assert candidate_multiplier("slippage_aware_sizing_v1", winner) == candidate_multiplier(
        "slippage_aware_sizing_v1", loser
    )


def test_evaluation_applies_round_trip_slippage_after_sizing():
    result = evaluate_candidate([signal_row(1.0)], "baseline_nfi", slippage_ratio_per_side=0.001)
    assert result["profit_after_slippage"] == 0.8
    assert result["raw_signals"] == 1
    assert result["allowed_signals"] == 1
