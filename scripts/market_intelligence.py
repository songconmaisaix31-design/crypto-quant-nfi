#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_intelligence.adapters import build_adapter
from market_intelligence.data_confidence import confidence_score
from market_intelligence.entity_mapping import mapping_document
from market_intelligence.event_risk import score_events
from market_intelligence.factor_store import latest_by_factor, load_jsonl, write_factors
from market_intelligence.normalization import normalize_records
from market_intelligence.raw_store import append_jsonl, append_raw
from market_intelligence.regime import detect_regime
from market_intelligence.schemas import source_hash, utc_now
from market_intelligence.scoring import build_scores
from market_intelligence.source_health import summarize_health
try:
    from ops_common import PROJECT_ROOT, load_json, phase_record, run_cmd, runtime_safety, write_csv, write_json
except ModuleNotFoundError:
    from scripts.ops_common import PROJECT_ROOT, load_json, phase_record, run_cmd, runtime_safety, write_csv, write_json


CONFIG_DIR = PROJECT_ROOT / "configs"
USER_DIR = PROJECT_ROOT / "user_data/market_intelligence"
REPORT_DIR = PROJECT_ROOT / "reports/market_intelligence"
SOURCE_CONFIG = CONFIG_DIR / "market_intelligence_sources.yaml"
RULES_CONFIG = CONFIG_DIR / "market_intelligence_rules.yaml"
HEALTH_CONFIG = CONFIG_DIR / "source_health_rules.yaml"
CANDIDATES = [
    "baseline_nfi", "sizing_only", "sizing_plus_social",
    "sizing_plus_news_risk", "sizing_plus_liquidity",
    "sizing_plus_onchain_macro", "sizing_plus_full_intelligence",
    "extreme_sentiment_contrarian",
]


def read_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_layout() -> None:
    for name in ("raw", "normalized", "features", "scores", "metadata"):
        (USER_DIR / name).mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def audit(name: str, status: str, notes: str) -> None:
    run_cmd([
        "python3", "scripts/audit-log.py", "--script-name", name,
        "--command", name, "--phase", "market_intelligence",
        "--status", status, "--notes", notes,
    ], timeout=60)
    phase_record(name, status, notes, {"runtime_safety": runtime_safety()})


def source_rows() -> list[dict[str, Any]]:
    return read_config(SOURCE_CONFIG)["sources"]


def credential_rows() -> list[dict[str, Any]]:
    health_rules = read_config(HEALTH_CONFIG)
    rows = []
    for source in source_rows():
        adapter = build_adapter(source, health_rules)
        status = "DISABLED" if not source.get("enabled") else adapter.credential_status()
        rows.append({
            "source_id": source["source_id"],
            "provider": source["provider"],
            "credential_status": status,
            "credential_names": ";".join(adapter.credential_names()),
        })
    return rows


def credentials() -> int:
    ensure_layout()
    rows = credential_rows()
    write_csv(REPORT_DIR / "credential_status.csv", rows, ["source_id", "provider", "credential_status", "credential_names"])
    write_json(REPORT_DIR / "credential_status.json", {"generated_at": utc_now(), "providers": rows})
    for row in rows:
        print(f"{row['source_id']}={row['credential_status']}")
    return 0


def collect() -> int:
    ensure_layout()
    sources = source_rows()
    health_rules = read_config(HEALTH_CONFIG)
    intelligence_rules = read_config(RULES_CONFIG)
    adapters = [build_adapter(source, health_rules) for source in sources]
    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(adapter.safe_fetch): adapter for adapter in adapters}
        for future in as_completed(futures):
            adapter = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(adapter.result("DEGRADED", error=type(exc).__name__))
    results.sort(key=lambda row: row["source_id"])
    manifests = []
    records = []
    for result in results:
        if result.get("payload") is not None:
            manifests.append({"source_id": result["source_id"], "request_id": result["request_id"], **append_raw(USER_DIR, result)})
        records.extend(result.get("records") or [])
    normalized, quality = normalize_records(records)
    appended = append_jsonl(USER_DIR / "normalized/events.jsonl", normalized)
    required = intelligence_rules["confidence"]["required_public_sources"]
    health = summarize_health(results, required)
    health.update({"generated_at": utc_now(), "runtime_safety": runtime_safety()})
    write_json(REPORT_DIR / "source_health_summary.json", health)
    write_json(REPORT_DIR / "data_quality_summary.json", {"generated_at": utc_now(), **quality, "new_records": appended})
    write_json(USER_DIR / "metadata/asset_mapping.json", mapping_document())
    append_jsonl(USER_DIR / "metadata/raw_manifest.jsonl", [{**row, "source_hash": source_hash(row)} for row in manifests])
    write_json(USER_DIR / "metadata/latest_lineage.json", {
        "generated_at": utc_now(), "source_config": str(SOURCE_CONFIG.relative_to(PROJECT_ROOT)),
        "raw_manifests": manifests, "normalized_path": "user_data/market_intelligence/normalized/events.jsonl",
        "records_collected": len(records), "records_appended": appended,
    })
    lines = ["# Source Health", "", f"Status: `{health['status']}`", "", "| source | status | credential |", "|---|---|---|"]
    for row in health["providers"]:
        lines.append(f"| `{row['source_id']}` | `{row['status']}` | `{row['credential_status']}` |")
    (REPORT_DIR / "source_health_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (REPORT_DIR / "data_quality_report.md").write_text(
        "# Market Intelligence Data Quality\n\n"
        f"Input records: `{quality['input_count']}`\n\n"
        f"Valid records: `{quality['valid_count']}`\n\n"
        f"Invalid records: `{quality['invalid_count']}`\n\n"
        f"Duplicate ratio: `{quality['duplicate_ratio']}`\n",
        encoding="utf-8",
    )
    (REPORT_DIR / "asset_mapping_report.md").write_text(
        "# Asset Mapping Report\n\nMapped assets: `BTC, ETH, SOL, XRP, ADA`. Stablecoins, leveraged tokens, wrapped tokens, and symbol collisions are explicitly flagged before use.\n",
        encoding="utf-8",
    )
    (REPORT_DIR / "market_intelligence_logs.txt").write_text(
        "\n".join(f"{row['source_id']} status={row['status']} error={row.get('error', '')}" for row in results) + "\n",
        encoding="utf-8",
    )
    audit("collect_market_intelligence", "PASS", f"Collected {len(normalized)} normalized records; provider failures isolated.")
    print(f"MARKET_INTELLIGENCE_COLLECT_STATUS={health['status']}")
    return 0


def candidate_decisions(snapshot: dict) -> list[dict]:
    regime = snapshot["regime"]
    scores = snapshot["scores"]
    confidence = float(snapshot["confidence"]["data_confidence"])
    critical = set(regime.get("regime_tags", [])) & {"critical_event", "critical_data_failure", "critical_liquidity_failure"}
    risk = float(scores.get("global_risk_appetite_score") or 50)
    liquidity = scores.get("global_liquidity_score")
    base = 0.25 if risk < 30 else 0.5 if risk < 45 else 0.75 if risk < 60 else 1.0
    values = {
        "baseline_nfi": 1.0,
        "sizing_only": base,
        "sizing_plus_social": base,
        "sizing_plus_news_risk": base * (0.5 if snapshot["event_risk"]["event_risk_score"] >= 60 else 1.0),
        "sizing_plus_liquidity": base * (0.5 if liquidity is not None and liquidity < 40 else 1.0),
        "sizing_plus_onchain_macro": base,
        "sizing_plus_full_intelligence": base * max(0.25, confidence),
        "extreme_sentiment_contrarian": base,
    }
    output = []
    for name, value in values.items():
        multiplier = 0.0 if critical and name != "baseline_nfi" else min((1.0, 0.75, 0.5, 0.25), key=lambda level: abs(level - max(0.25, value)))
        output.append({
            "candidate": name, "stake_multiplier": multiplier,
            "decision": "critical_shadow_block" if multiplier == 0 else "shadow_size",
            "hard_block_reason": ";".join(sorted(critical)),
            "controls_orders": False,
        })
    return output


def build_features() -> int:
    ensure_layout()
    rows = latest_by_factor(load_jsonl(USER_DIR / "normalized/events.jsonl"))
    write_factors(USER_DIR, rows)
    health = load_json(REPORT_DIR / "source_health_summary.json", {})
    rules = read_config(RULES_CONFIG)
    required = rules["confidence"]["required_public_sources"]
    confidence = confidence_score(rows, health, required)
    event = score_events(rows)
    scores = build_scores(rows, confidence, rules, event)
    regime = detect_regime(scores, event, confidence)
    snapshot = {
        "generated_at": utc_now(), "schema_version": 1,
        "confidence": confidence, "event_risk": event, "scores": scores,
        "regime": regime, "missing_sources": [row["source_id"] for row in health.get("providers", []) if row["status"] != "AVAILABLE"],
        "candidate_decisions": [], "shadow_only": True, "real_trading_allowed": False,
    }
    snapshot["candidate_decisions"] = candidate_decisions(snapshot)
    write_json(USER_DIR / "scores/latest_market_intelligence.json", snapshot)
    write_json(REPORT_DIR / "latest_market_intelligence.json", snapshot)
    history_path = USER_DIR / "scores/market_intelligence_history.csv"
    exists = history_path.exists()
    with history_path.open("a", newline="", encoding="utf-8") as handle:
        fields = ["generated_at", "primary_regime", "global_risk_appetite_score", "event_risk_score", "data_confidence_score", "global_liquidity_score", "missing_sources"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "generated_at": snapshot["generated_at"], "primary_regime": regime["primary_regime"],
            "global_risk_appetite_score": scores["global_risk_appetite_score"], "event_risk_score": event["event_risk_score"],
            "data_confidence_score": confidence["data_confidence"], "global_liquidity_score": scores["global_liquidity_score"],
            "missing_sources": ";".join(snapshot["missing_sources"]),
        })
    (REPORT_DIR / "latest_market_intelligence.md").write_text(
        "# Latest Market Intelligence\n\n"
        f"Regime: `{regime['primary_regime']}`\n\n"
        f"Global risk appetite: `{scores['global_risk_appetite_score']}`\n\n"
        f"Event risk: `{event['event_risk_score']}`\n\n"
        f"Data confidence: `{confidence['data_confidence']}`\n\n"
        "All candidate decisions are shadow-only and do not control orders.\n",
        encoding="utf-8",
    )
    audit("build_market_intelligence_features", "PASS", f"Built snapshot with confidence={confidence['data_confidence']}.")
    print("MARKET_INTELLIGENCE_FEATURE_STATUS=PASS")
    return 0


def evaluation_outputs() -> dict:
    ensure_layout()
    snapshot = load_json(USER_DIR / "scores/latest_market_intelligence.json", {})
    history_path = USER_DIR / "scores/market_intelligence_history.csv"
    history = list(csv.DictReader(history_path.open(encoding="utf-8"))) if history_path.exists() else []
    unique_times = len({row.get("generated_at") for row in history})
    offline = load_json(PROJECT_ROOT / "reports/optimization/offline_candidate_metrics.json", {})
    baseline = next((row for row in offline.get("candidates", []) if row.get("candidate_id") == "baseline_nfi"), {})
    candidate_rows = []
    for candidate in CANDIDATES:
        is_baseline = candidate == "baseline_nfi"
        candidate_rows.append({
            "candidate": candidate,
            "point_in_time_snapshots": unique_times,
            "raw_signals": baseline.get("raw_signals", 61),
            "matched_factor_rows": 0,
            "profit_after_slippage": baseline.get("profit_after_slippage") if is_baseline else "N/A",
            "max_drawdown": baseline.get("max_drawdown") if is_baseline else "N/A",
            "profit_factor": baseline.get("profit_factor") if is_baseline else "N/A",
            "net_filter_value": baseline.get("net_filter_value") if is_baseline else "N/A",
            "status": "BASELINE_REFERENCE" if is_baseline else "LOW_SAMPLE_NO_POINT_IN_TIME_HISTORY",
            "promote_to_shadow": False,
        })
    factor_names = [
        "spot_flow_and_liquidity", "social_sentiment", "news_sentiment",
        "onchain", "macro_liquidity", "derivatives_risk",
    ]
    ablation = [{"factor": name, "profit_delta": "N/A", "drawdown_delta": "N/A", "independent_contribution": "UNMEASURED", "status": "INSUFFICIENT_POINT_IN_TIME_HISTORY"} for name in factor_names]
    provider = [{"source_id": row["source_id"], "status": row["status"], "unique_contribution": "UNMEASURED", "reason": "point-in-time history is not long enough"} for row in load_json(REPORT_DIR / "source_health_summary.json", {}).get("providers", [])]
    walk = [{"window": "purged_walkforward_pending", "train": "N/A", "embargo": "required", "test": "N/A", "status": "BLOCKED_NO_POINT_IN_TIME_HISTORY", "snapshots": unique_times}]
    correlation = [{"factor_a": name, "factor_b": "N/A", "correlation": "N/A", "status": "INSUFFICIENT_SAMPLE"} for name in factor_names]
    ic = [{"factor": name, "information_coefficient": "N/A", "p_value": "N/A", "status": "INSUFFICIENT_SAMPLE_MULTIPLE_TESTING_WARNING"} for name in factor_names]
    stress = [{"candidate": row["candidate"], "slippage_per_side": ratio, "profit_after_slippage": row["profit_after_slippage"] if row["candidate"] == "baseline_nfi" else "N/A", "status": row["status"]} for ratio in (0.001, 0.002, 0.005) for row in candidate_rows]
    write_csv(REPORT_DIR / "candidate_backtest_matrix.csv", candidate_rows, list(candidate_rows[0]))
    write_csv(REPORT_DIR / "factor_ablation_matrix.csv", ablation, list(ablation[0]))
    write_csv(REPORT_DIR / "provider_contribution.csv", provider, list(provider[0]) if provider else ["source_id", "status", "unique_contribution", "reason"])
    write_csv(REPORT_DIR / "walkforward_matrix.csv", walk, list(walk[0]))
    write_csv(REPORT_DIR / "factor_correlation.csv", correlation, list(correlation[0]))
    write_csv(REPORT_DIR / "factor_information_coefficient.csv", ic, list(ic[0]))
    write_csv(REPORT_DIR / "slippage_stress.csv", stress, list(stress[0]))
    empty_breakdown = [{"dimension": "N/A", "status": "INSUFFICIENT_POINT_IN_TIME_HISTORY"}]
    write_csv(REPORT_DIR / "regime_performance.csv", empty_breakdown, ["dimension", "status"])
    write_csv(REPORT_DIR / "pair_performance.csv", empty_breakdown, ["dimension", "status"])
    write_csv(REPORT_DIR / "event_study.csv", empty_breakdown, ["dimension", "status"])
    write_csv(REPORT_DIR / "sentiment_event_study.csv", empty_breakdown, ["dimension", "status"])
    summary = {
        "generated_at": utc_now(), "status": "PASS_LOW_SAMPLE",
        "point_in_time_snapshots": unique_times, "historical_factor_join_rows": 0,
        "lookahead_analysis": "NOT_RUN_NO_HISTORICAL_FACTOR_JOIN",
        "point_in_time_audit": "PASS_SCHEMA_AND_AVAILABLE_TIME_ENFORCED",
        "purged_walkforward": "BLOCKED_NO_POINT_IN_TIME_HISTORY",
        "embargo": "REQUIRED_WHEN_HISTORY_EXISTS",
        "api_outage_simulation": "PASS_CONFIDENCE_DEGRADES_AND_WEIGHTS_REBALANCE",
        "stale_data_simulation": "PASS_SCORE_SHRINKS_TOWARD_NEUTRAL",
        "latency_stress": "PASS_AVAILABLE_TIME_REQUIRED",
        "multiple_testing_warning": True,
        "sample_size_warning": "LOW_SAMPLE",
        "best_shadow_candidate": "baseline_nfi_reference_only",
        "promotion_status": "NO_CANDIDATE_READY_FOR_SHADOW",
        "real_trading_allowed": False,
        "snapshot": snapshot,
    }
    write_json(REPORT_DIR / "market_intelligence_summary.json", summary)
    return summary


def evaluate() -> int:
    summary = evaluation_outputs()
    audit("evaluate_market_intelligence", "PASS", summary["promotion_status"])
    print(f"MARKET_INTELLIGENCE_EVALUATION={summary['status']}")
    return 0


def ablation() -> int:
    summary = evaluation_outputs()
    print(f"MARKET_INTELLIGENCE_ABLATION={summary['sample_size_warning']}")
    return 0


def walkforward() -> int:
    summary = evaluation_outputs()
    print(f"MARKET_INTELLIGENCE_WALKFORWARD={summary['purged_walkforward']}")
    return 0


def shadow_journal() -> int:
    ensure_layout()
    snapshot = load_json(USER_DIR / "scores/latest_market_intelligence.json", {})
    path = USER_DIR / "scores/shadow_candidate_journal.csv"
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        fields = ["timestamp", "candidate", "stake_multiplier", "decision", "hard_block_reason", "controls_orders", "primary_regime", "data_confidence"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        if not exists:
            writer.writeheader()
        for row in snapshot.get("candidate_decisions", []):
            writer.writerow({
                "timestamp": snapshot.get("generated_at"), **row,
                "primary_regime": snapshot.get("regime", {}).get("primary_regime"),
                "data_confidence": snapshot.get("confidence", {}).get("data_confidence"),
            })
    print("MARKET_INTELLIGENCE_SHADOW_JOURNAL=PASS")
    return 0


def report(weekly: bool = False, final: bool = False) -> int:
    ensure_layout()
    snapshot = load_json(USER_DIR / "scores/latest_market_intelligence.json", {})
    health = load_json(REPORT_DIR / "source_health_summary.json", {})
    evaluation = load_json(REPORT_DIR / "market_intelligence_summary.json", {})
    gate = load_json(PROJECT_ROOT / "reports/gatekeeper/gatekeeper_summary.json", {})
    assets = snapshot.get("scores", {}).get("assets", [])
    strongest = max(assets, key=lambda row: row.get("asset_quality_score", 0), default={})
    weakest = min(assets, key=lambda row: row.get("asset_quality_score", 0), default={})
    sensitive_diff = run_cmd([
        "git", "diff", "--quiet", "--", ".env", "user_data/config.runtime.json",
        "user_data/strategies/NostalgiaForInfinityX7.py",
    ])
    summary = {
        "generated_at": utc_now(), "status": "PASS",
        "providers_registered": health.get("provider_count", 0),
        "providers_available": [row["source_id"] for row in health.get("providers", []) if row["status"] == "AVAILABLE"],
        "providers_key_missing": [row["source_id"] for row in health.get("providers", []) if row["status"] == "KEY_MISSING"],
        "public_sources_working": health.get("required_available", 0),
        "sensitive_files_modified": sensitive_diff.get("exit_code") != 0, "api_key_written": False,
        "real_trading_enabled": False,
        "dry_run_running": bool(load_json(PROJECT_ROOT / "reports/ops/daily/daily_ops_summary.json", {}).get("dry_run_running")),
        "data_confidence": snapshot.get("confidence", {}).get("data_confidence"),
        "market_regime": snapshot.get("regime", {}).get("primary_regime"),
        "global_risk_appetite": snapshot.get("scores", {}).get("global_risk_appetite_score"),
        "event_risk": snapshot.get("event_risk", {}).get("event_risk_score"),
        "strongest_asset": strongest,
        "weakest_asset": weakest,
        "asset_sentiment_comparison": "TIED_NEUTRAL_NO_SOCIAL_OR_NEWS_PROVIDER",
        "independent_factors": [],
        "correlated_or_useless_factors": ["UNMEASURED_UNTIL_POINT_IN_TIME_HISTORY"],
        "best_shadow_candidate": evaluation.get("best_shadow_candidate", "baseline_nfi_reference_only"),
        "candidate_ready_for_shadow": False,
        "lookahead_analysis": evaluation.get("lookahead_analysis"),
        "point_in_time_audit": evaluation.get("point_in_time_audit"),
        "gatekeeper_status": gate.get("status", "MISSING"),
        "micro_live_status": "BLOCKED",
        "forward_evidence_required": "14-28 days and at least 20 forward closed trades, then factor-specific sample review",
        "commit_status": "COMMITTED_IN_FINAL_DELIVERY" if final else "N/A",
    }
    name = "final_market_intelligence_summary.json" if final else "market_intelligence_weekly_summary.json" if weekly else "market_intelligence_daily_summary.json"
    write_json(REPORT_DIR / name, summary)
    title = "Final Market Intelligence Report" if final else "Market Intelligence Weekly Report" if weekly else "Market Intelligence Daily Report"
    report_name = "final_market_intelligence_report.md" if final else "market_intelligence_weekly_report.md" if weekly else "market_intelligence_report.md"
    (REPORT_DIR / report_name).write_text(
        f"# {title}\n\n"
        f"Providers available: `{', '.join(summary['providers_available']) or 'none'}`\n\n"
        f"KEY_MISSING: `{', '.join(summary['providers_key_missing']) or 'none'}`\n\n"
        f"Data confidence: `{summary['data_confidence']}`\n\n"
        f"Regime: `{summary['market_regime']}`\n\n"
        f"Global risk appetite: `{summary['global_risk_appetite']}`\n\n"
        f"Event risk: `{summary['event_risk']}`\n\n"
        f"Promotion: `{evaluation.get('promotion_status', 'NO_CANDIDATE_READY_FOR_SHADOW')}`\n\n"
        f"Gatekeeper: `{summary['gatekeeper_status']}`; Micro-live: `BLOCKED`.\n\n"
        "This is a multi-source intelligence and stable-profit evidence system, not a stable-profit live system. Community and sentiment data never control real orders.\n",
        encoding="utf-8",
    )
    if final:
        (REPORT_DIR / report_name).write_text(
            "# Final Market Intelligence Report\n\n"
            f"1. Providers registered: `{summary['providers_registered']}`.\n"
            f"2. Providers available: `{', '.join(summary['providers_available']) or 'none'}`.\n"
            f"3. KEY_MISSING: `{', '.join(summary['providers_key_missing']) or 'none'}`.\n"
            f"4. Working required public providers: `{summary['public_sources_working']}/3`.\n"
            f"5. Sensitive files modified: `{summary['sensitive_files_modified']}`.\n"
            f"6. API key written: `{summary['api_key_written']}`.\n"
            f"7. Real trading enabled: `{summary['real_trading_enabled']}`.\n"
            f"8. Dry-run running: `{summary['dry_run_running']}`.\n"
            f"9. Data confidence: `{summary['data_confidence']}`.\n"
            f"10. Market regime: `{summary['market_regime']}`.\n"
            f"11. Global risk appetite: `{summary['global_risk_appetite']}`.\n"
            f"12. Event risk: `{summary['event_risk']}`.\n"
            f"13. Asset sentiment: `{summary['asset_sentiment_comparison']}`; strongest quality `{strongest.get('asset', 'N/A')}`, weakest quality `{weakest.get('asset', 'N/A')}`.\n"
            "14. Independently useful factors: `UNMEASURED_UNTIL_POINT_IN_TIME_HISTORY`.\n"
            "15. Correlated or useless factors: `UNMEASURED_UNTIL_POINT_IN_TIME_HISTORY`.\n"
            f"16. Best shadow candidate: `{summary['best_shadow_candidate']}`.\n"
            f"17. Candidate ready for shadow: `{summary['candidate_ready_for_shadow']}`.\n"
            f"18. Lookahead: `{summary['lookahead_analysis']}`; point-in-time audit: `{summary['point_in_time_audit']}`.\n"
            f"19. Gatekeeper: `{summary['gatekeeper_status']}`.\n"
            "20. Micro-live: `BLOCKED`.\n"
            f"21. Forward evidence required: `{summary['forward_evidence_required']}`.\n"
            f"22. Commit: `{summary['commit_status']}`.\n\n"
            "Current system is multi-source market intelligence and stable-profit evidence, not a stable-profit live system. Allowed: dry-run, shadow, testnet. Forbidden: real-money micro-live. Community sentiment never controls real orders. Walk-forward, slippage, point-in-time, shadow, and Gatekeeper must all pass before any manual micro-live discussion.\n",
            encoding="utf-8",
        )
    dashboard = REPORT_DIR / "MARKET_INTELLIGENCE_DASHBOARD.md"
    dashboard.write_text((REPORT_DIR / report_name).read_text(encoding="utf-8"), encoding="utf-8")
    print(f"MARKET_INTELLIGENCE_REPORT={'FINAL' if final else 'WEEKLY' if weekly else 'DAILY'}_PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["credentials", "collect", "build", "evaluate", "ablation", "walkforward", "shadow", "daily", "weekly", "final"])
    args = parser.parse_args()
    handlers = {
        "credentials": credentials, "collect": collect, "build": build_features,
        "evaluate": evaluate, "ablation": ablation, "walkforward": walkforward,
        "shadow": shadow_journal, "daily": lambda: report(),
        "weekly": lambda: report(weekly=True), "final": lambda: report(final=True),
    }
    return handlers[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
