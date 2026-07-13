import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evidence_throughput_controller import (  # noqa: E402
    choose_status,
    estimate_eta_days,
    summarize_sample_viability,
    unique_baseline_events,
    unique_closed_outcomes,
)
from shadow_decision_journal import closed_trade_transitions  # noqa: E402


def test_evidence_counts_ignore_heartbeats_and_candidate_duplicates():
    rows = [
        {"candidate_name": "baseline_nfi", "event_type": "heartbeat", "snapshot_time": "2026-07-13T00:00:00+00:00"},
        {"candidate_name": "baseline_nfi", "event_type": "dry_run_trade", "dry_run_trade_id": "7", "snapshot_time": "2026-07-13T01:00:00+00:00"},
        {"candidate_name": "decision_engine_v2_frozen", "event_type": "dry_run_trade", "dry_run_trade_id": "7", "snapshot_time": "2026-07-13T01:00:00+00:00"},
        {"candidate_name": "baseline_nfi", "event_type": "dry_run_trade_closed", "dry_run_trade_id": "7", "dry_run_close_profit": "0.01", "snapshot_time": "2026-07-13T02:00:00+00:00"},
        {"candidate_name": "decision_engine_v2_frozen", "event_type": "dry_run_trade_closed", "dry_run_trade_id": "7", "dry_run_close_profit": "0.01", "snapshot_time": "2026-07-13T02:00:00+00:00"},
    ]
    assert len(unique_baseline_events(rows, {"dry_run_trade", "signal_replay"})) == 1
    assert len(unique_closed_outcomes(rows)) == 1


def test_eta_uses_slower_sample_requirement_and_zero_rate_is_unbounded():
    assert estimate_eta_days(5, 20, 3.0, 10, 14, True) == 5
    assert estimate_eta_days(0, 20, 0.0, 0, 14, True) is None
    assert estimate_eta_days(20, 20, 1.0, 14, 14, True) == 0


def test_status_distinguishes_blocked_starved_and_quality_blocked():
    safe_running = {"running": True, "safety": {"pass": True}}
    stopped = {"running": False, "safety": {"pass": True}}
    assert choose_status(stopped, 0, 20, 0, 0, 14, False)[0] == "EVIDENCE_BLOCKED"
    assert choose_status(safe_running, 0, 20, 0, 1, 14, False)[0] == "EVIDENCE_STARVED"
    assert choose_status(safe_running, 20, 20, 1, 14, 14, False)[0] == "QUALITY_BLOCKED"
    assert choose_status(safe_running, 20, 20, 1, 14, 14, True)[0] == "READY_FOR_SHADOW_REVIEW"


def test_open_to_closed_transition_is_recorded_once():
    trades = [
        {"id": 1, "is_open": False, "close_profit": 0.02},
        {"id": 2, "is_open": True, "close_profit": None},
    ]
    previous = {"1": {"is_open": True}, "2": {"is_open": True}}
    assert [trade["id"] for trade in closed_trade_transitions(trades, previous)] == [1]


def test_sample_viability_is_reused_without_claiming_profitability():
    sample = {
        "generated_at": "2026-07-06T00:00:00+00:00",
        "runtime_config_untouched": True,
        "groups": [
            {"group": "base_365d", "pair_count": 5, "days": 365, "trades_count": 8},
            {"group": "expanded_180d", "pair_count": 20, "days": 180, "trades_count": 21},
            {"group": "expanded_365d", "pair_count": 20, "days": 365, "trades_count": 61},
        ],
    }
    result = summarize_sample_viability(sample)
    assert result["signal_viability_proven"] is True
    assert result["profitability_proven"] is False
    assert result["pair_count"] == 20
    assert result["entries_180d"] == 21
    assert result["entries_365d"] == 61
    assert result["projected_days_to_entry_target"] == 120
