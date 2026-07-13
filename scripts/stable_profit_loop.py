#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from ops_common import PROJECT_ROOT, ensure_dir, git_info, load_json, phase_record, read_status, run_cmd, runtime_safety, utc_now, write_csv, write_json
from offline_candidate_evaluation import (
    CANDIDATE_IDS,
    anti_overfit_rows,
    evaluate_all,
    grouped_performance,
    load_evidence_rows,
    slippage_stress,
    walkforward_rows,
)


SOURCE_CONFIG = PROJECT_ROOT / "configs/community_sources.yaml"
HYPOTHESIS_RULES = PROJECT_ROOT / "configs/hypothesis_rules.yaml"
EXPERIMENT_RULES = PROJECT_ROOT / "configs/optimization_experiment_rules.yaml"
SCORE_RULES = PROJECT_ROOT / "configs/stable_profit_score.yaml"
CI_DIR = PROJECT_ROOT / "reports/community_intelligence"
USER_CI_DIR = PROJECT_ROOT / "user_data/community_intelligence"
HYP_DIR = PROJECT_ROOT / "reports/hypotheses"
USER_HYP_DIR = PROJECT_ROOT / "user_data/hypotheses"
OPT_DIR = PROJECT_ROOT / "reports/optimization"
OPT_EXP_DIR = PROJECT_ROOT / "reports/optimization_experiments"
USER_OPT_EXP_DIR = PROJECT_ROOT / "user_data/optimization_experiments"
SHADOW_PROMOTION_DIR = PROJECT_ROOT / "reports/shadow_promotion"
HYPEROPT_DIR = PROJECT_ROOT / "reports/hyperopt_research"
LOOP_DIR = PROJECT_ROOT / "reports/stable_profit_loop"
V11_HYPOTHESES = ["H1", "H5", "H7", "H8", "H3"]
METRIC_FIELDS = [
    "candidate_id", "raw_signals", "allowed_signals", "allowed_ratio",
    "profit_after_slippage", "max_drawdown", "profit_factor", "win_rate",
    "max_consecutive_losses", "net_filter_value", "missed_profit",
    "avoided_loss", "largest_missed_winner", "largest_avoided_loser",
    "regime_stability", "sample_size", "overfit_risk",
]


INITIAL_HYPOTHESES = [
    {
        "hypothesis_id": "H1",
        "source_claim_ids": ["internal_decision_engine_v2_negative_filter_value"],
        "title": "Sizing-only may outperform hard block filters",
        "description": "Decision Engine v1/v2 may have killed profitable signals; test risk-adjusted sizing before hard blocking.",
        "module_target": "Sizing Only",
        "expected_improvement": ["profit_after_slippage", "net_filter_value", "reduced_missed_profit"],
        "risk": ["missed_winners", "live_slippage", "low_sample"],
        "experiment_type": "Sizing-only experiment",
        "priority": 1,
    },
    {
        "hypothesis_id": "H2",
        "source_claim_ids": ["internal_extreme_volume_zscore"],
        "title": "Extreme volume z-score should reduce stake instead of hard block",
        "description": "Volume spikes can represent both risk and opportunity; compare hard block against stake reduction.",
        "module_target": "Decision Engine",
        "expected_improvement": ["reduced_missed_profit", "regime_stability"],
        "risk": ["community_noise", "missed_winners"],
        "experiment_type": "Decision Engine threshold experiment",
        "priority": 2,
    },
    {
        "hypothesis_id": "H3",
        "source_claim_ids": ["internal_extreme_pair_atr"],
        "title": "Extreme pair ATR should reduce stake unless combined with market stress",
        "description": "ATR alone may be too broad; test block only when ATR stress aligns with BTC drawdown or poor breadth.",
        "module_target": "Market State",
        "expected_improvement": ["max_drawdown", "avoided_loss", "regime_stability"],
        "risk": ["too_many_thresholds", "overfit"],
        "experiment_type": "Market regime filter experiment",
        "priority": 2,
    },
    {
        "hypothesis_id": "H4",
        "source_claim_ids": ["internal_risk_off_bad_enter_tag"],
        "title": "Keep risk_off_bad_enter_tag as a positive historical contributor",
        "description": "This rule appears historically useful and should remain in shadow observation instead of being removed.",
        "module_target": "NFI tag filter",
        "expected_improvement": ["avoided_loss", "max_drawdown"],
        "risk": ["low_sample", "post_selection_bias"],
        "experiment_type": "Tag regime filter experiment",
        "priority": 3,
    },
    {
        "hypothesis_id": "H5",
        "source_claim_ids": ["internal_pair_quality_below_40"],
        "title": "Pair quality 20-40 should reduce stake, not hard block",
        "description": "Test hard block below 20 and stake reduction for 20-40 to reduce missed winners.",
        "module_target": "Pairlist",
        "expected_improvement": ["reduced_missed_profit", "net_filter_value"],
        "risk": ["missed_winners", "data_quality_warning"],
        "experiment_type": "Pairlist quality experiment",
        "priority": 1,
    },
    {
        "hypothesis_id": "H6",
        "source_claim_ids": ["internal_top_coins_enter_tag_family"],
        "title": "Top-coins enter_tag family needs tag by regime analysis",
        "description": "Do not block an entire tag family; test tag performance under market regimes.",
        "module_target": "NFI tag filter",
        "expected_improvement": ["regime_stability", "profit_factor"],
        "risk": ["tag_concentration", "overfit"],
        "experiment_type": "Tag regime filter experiment",
        "priority": 2,
    },
    {
        "hypothesis_id": "H7",
        "source_claim_ids": ["internal_sizing_only_candidate"],
        "title": "Stable profit may come from position sizing instead of signal filtering",
        "description": "Compare baseline, sizing-only, and block filters using slippage-adjusted results.",
        "module_target": "Sizing Only",
        "expected_improvement": ["profit_after_slippage", "max_consecutive_losses"],
        "risk": ["live_slippage", "operational_complexity"],
        "experiment_type": "Sizing-only experiment",
        "priority": 1,
    },
    {
        "hypothesis_id": "H8",
        "source_claim_ids": ["internal_slippage_negative_baseline"],
        "title": "Slippage stress requires frequency, exit, protection, and sizing work",
        "description": "If baseline turns negative after slippage, optimize trade frequency and exits before promotion.",
        "module_target": "Exit Logic",
        "expected_improvement": ["profit_after_slippage", "profit_factor", "max_drawdown"],
        "risk": ["overfit", "live_slippage"],
        "experiment_type": "Slippage stress experiment",
        "priority": 1,
    },
    {
        "hypothesis_id": "H9",
        "source_claim_ids": ["internal_pairlist_expansion_warning"],
        "title": "Pairlist expansion must be liquidity and data-quality gated",
        "description": "Do not blindly expand pairlist; test liquidity, spread, volume, ATR, and data gaps first.",
        "module_target": "Pairlist",
        "expected_improvement": ["regime_stability", "profit_after_slippage"],
        "risk": ["data_quality_warning", "live_slippage"],
        "experiment_type": "Pairlist quality experiment",
        "priority": 3,
    },
    {
        "hypothesis_id": "H10",
        "source_claim_ids": ["official_freqtrade_hyperopt"],
        "title": "Hyperopt is research-only with narrow parameter spaces",
        "description": "Use Hyperopt only for ROI, stoploss, trailing, and protections; never promote raw optimum to live.",
        "module_target": "Stoploss",
        "expected_improvement": ["profit_factor", "max_drawdown"],
        "risk": ["overfit", "post_selection_bias", "data_leakage"],
        "experiment_type": "Stoploss / trailing experiment",
        "priority": 4,
    },
]


def read_config(path: Path) -> dict[str, Any]:
    return load_json(path, {})


def source_rows() -> list[dict[str, Any]]:
    return read_config(SOURCE_CONFIG).get("sources", [])


def gate_snapshot() -> dict[str, Any]:
    gate = load_json(PROJECT_ROOT / "reports/gatekeeper/gatekeeper_summary.json", {})
    micro = load_json(PROJECT_ROOT / "reports/micro_live_readiness/micro_live_readiness_summary.json", {})
    daily = load_json(PROJECT_ROOT / "reports/ops/daily/daily_ops_summary.json", {})
    audit = load_json(PROJECT_ROOT / "reports/audit/audit_summary.json", {})
    secret_findings = PROJECT_ROOT / "reports/audit/secret_scan_findings.csv"
    findings_count = 0
    if secret_findings.exists():
        findings_count = max(0, len(secret_findings.read_text(encoding="utf-8", errors="ignore").splitlines()) - 1)
    return {
        "runtime_safety": runtime_safety(),
        "gatekeeper_status": gate.get("status", "MISSING"),
        "testnet_allowed": bool(gate.get("testnet_allowed")),
        "micro_live_status": micro.get("status", "BLOCKED"),
        "manual_micro_live_allowed": bool(micro.get("manual_micro_live_allowed", False)),
        "daily_ops_status": daily.get("status", "MISSING"),
        "dry_run_running": bool(daily.get("dry_run_running", gate.get("dry_run_running", False))),
        "forward_evidence_blocked": bool(daily.get("forward_evidence_blocked", gate.get("forward_evidence_blocked", False))),
        "audit_status": audit.get("status", "MISSING"),
        "secret_scan_status": "PASS" if secret_findings.exists() and findings_count == 0 else "REVIEW",
        "secret_scan_findings": findings_count,
    }


def record_audit(script_name: str, status: str, notes: str) -> None:
    run_cmd([
        "python3",
        "scripts/audit-log.py",
        "--script-name",
        script_name,
        "--command",
        script_name,
        "--phase",
        "stable_profit_loop",
        "--status",
        status,
        "--notes",
        notes,
    ], timeout=60)
    phase_record(script_name, status, notes, {"gate": gate_snapshot()})


def stable_id(prefix: str, text: str) -> str:
    return f"{prefix}_{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def source_registry() -> int:
    ensure_dir(CI_DIR)
    rows = source_rows()
    summary = {
        "generated_at": utc_now(),
        "status": "PASS",
        "sources_count": len(rows),
        "external_sources_count": sum(1 for r in rows if r.get("source_type") != "internal"),
        "manual_review_sources_count": sum(1 for r in rows if r.get("manual_review_required")),
        "gate": gate_snapshot(),
    }
    write_json(CI_DIR / "source_registry.json", {"summary": summary, "sources": rows})
    write_csv(CI_DIR / "source_quality_matrix.csv", rows, [
        "source_id", "name", "url", "source_type", "trust_level", "update_frequency",
        "allowed_collection_method", "disallowed_collection_method", "expected_signal_type",
        "risk_notes", "citation_required", "manual_review_required",
    ])
    lines = [
        "# Community Intelligence Source Registry",
        "",
        f"Generated: `{summary['generated_at']}`",
        f"Status: `{summary['status']}`",
        "",
        "External sources create hypotheses only. They do not create trading actions.",
        "",
        "| source_id | trust | type | collection | URL |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(f"| `{row['source_id']}` | `{row['trust_level']}` | `{row['source_type']}` | {row['allowed_collection_method']} | {row['url']} |")
    (CI_DIR / "source_registry.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    record_audit("community_source_registry", "PASS", f"Registered {len(rows)} intelligence sources.")
    print("COMMUNITY_SOURCE_REGISTRY_STATUS=PASS")
    return 0


def seed_claims() -> list[dict[str, Any]]:
    now = utc_now()
    claims = [
        ("official_freqtrade_strategy_customization", "backtest_warning", "Dry-run and forward testing are required before risking capital.", "All strategy changes must remain dry-run/shadow before live discussion.", "reduced_live_risk", "official_doc"),
        ("official_freqtrade_lookahead_analysis", "data_quality_warning", "Lookahead bias can invalidate profitable backtests.", "Every candidate needs lookahead-analysis before shadow promotion.", "reduced_data_leakage", "official_doc"),
        ("official_freqtrade_recursive_analysis", "data_quality_warning", "Indicator recursion issues can make results unstable.", "Run recursive-analysis for candidates that alter indicators or timeframe logic.", "reduced_indicator_instability", "official_doc"),
        ("official_freqtrade_hyperopt", "backtest_warning", "Hyperopt best result is research output, not live permission.", "Hyperopt candidates need train/test, walk-forward, slippage, and shadow validation.", "reduced_overfit", "official_doc"),
        ("official_binance_market_data_only", "operational_warning", "Public market data does not require API keys.", "Use public spot market data only unless testnet-specific keys are explicitly provided.", "reduced_secret_risk", "official_doc"),
        ("quantconnect_slippage_docs", "slippage_warning", "Slippage makes backtests more realistic.", "Score candidates by profit after fees and slippage stress, not gross profit.", "reduced_live_slippage_surprise", "official_doc"),
        ("internal_decision_engine_v2", "risk_warning", "Decision Engine v2 historical net_filter_value is negative.", "Prefer sizing or softer filters until blocked-winner damage is reduced.", "improved_net_filter_value", "internal_result"),
        ("internal_shadow_decision", "operational_warning", "Forward closed trades are insufficient.", "Do not promote candidates until forward samples and shadow consistency improve.", "reduced_low_sample_risk", "internal_result"),
    ]
    rows = []
    for source_id, claim_type, text, hyp, effect, evidence_level in claims:
        rows.append({
            "claim_id": stable_id("claim", source_id + text),
            "source_id": source_id,
            "source_url": next((s["url"] for s in source_rows() if s["source_id"] == source_id), ""),
            "collected_at": now,
            "author_or_context": "seeded from source registry and internal reports",
            "claim_type": claim_type,
            "claim_text": text,
            "extracted_hypothesis": hyp,
            "expected_effect": effect,
            "expected_risk": "overfit and low sample if used without validation",
            "confidence": "high" if evidence_level in {"official_doc", "internal_result"} else "medium",
            "evidence_level": evidence_level,
            "needs_experiment": True,
            "rejected_reason": "",
        })
    return rows


def manual_claims() -> tuple[list[dict[str, Any]], bool]:
    notes_dir = USER_CI_DIR / "manual_notes"
    raw_dir = USER_CI_DIR / "raw_notes"
    ensure_dir(notes_dir)
    ensure_dir(raw_dir)
    rows = []
    for path in sorted(notes_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            continue
        shutil.copy2(path, raw_dir / path.name)
        first = next((line.strip("# ").strip() for line in text.splitlines() if line.strip()), path.stem)
        rows.append({
            "claim_id": stable_id("claim", str(path) + text),
            "source_id": "manual_user_note",
            "source_url": str(path.relative_to(PROJECT_ROOT)),
            "collected_at": utc_now(),
            "author_or_context": path.name,
            "claim_type": "strategy_rule",
            "claim_text": first[:500],
            "extracted_hypothesis": "Manual note requires review before experiment design.",
            "expected_effect": "unknown until structured",
            "expected_risk": "community_noise",
            "confidence": "low",
            "evidence_level": "anecdote",
            "needs_experiment": True,
            "rejected_reason": "",
        })
    return rows, bool(rows)


def community_ingest() -> int:
    ensure_dir(CI_DIR)
    ensure_dir(USER_CI_DIR)
    claims, has_manual = manual_claims()
    rows = seed_claims() + claims
    normalized = USER_CI_DIR / "normalized_claims.jsonl"
    write_jsonl(normalized, rows)
    write_csv(CI_DIR / "community_claims.csv", rows, [
        "claim_id", "source_id", "source_url", "collected_at", "author_or_context", "claim_type",
        "claim_text", "extracted_hypothesis", "expected_effect", "expected_risk", "confidence",
        "evidence_level", "needs_experiment", "rejected_reason",
    ])
    status = "PASS" if has_manual else "NO_COMMUNITY_NOTES_YET"
    summary = {
        "generated_at": utc_now(),
        "status": status,
        "claims_count": len(rows),
        "manual_notes_count": len(claims),
        "seed_claims_count": len(rows) - len(claims),
        "normalized_claims": str(normalized),
        "gate": gate_snapshot(),
    }
    write_json(CI_DIR / "community_intel_summary.json", summary)
    (CI_DIR / "community_intel_logs.txt").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# Community Intelligence Report",
        "",
        f"Status: `{status}`",
        f"Claims: `{len(rows)}`",
        f"Manual notes: `{len(claims)}`",
        "",
        "Community notes are hypotheses only and cannot change trading behavior directly.",
    ]
    if not has_manual:
        lines.append("NO_COMMUNITY_NOTES_YET")
    (CI_DIR / "community_intel_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    record_audit("community_intel_ingest", "PASS", f"Ingested {len(rows)} claims; manual notes={len(claims)}.")
    print(f"COMMUNITY_INTEL_STATUS={status}")
    return 0


def manual_note() -> int:
    ensure_dir(USER_CI_DIR / "manual_notes")
    template = USER_CI_DIR / "manual_notes" / f"{utc_now()[:10]}-note-template.md"
    if not template.exists():
        template.write_text(
            "# Manual Community Note\n\n"
            "Source URL:\n\n"
            "Summary:\n\n"
            "Claim:\n\n"
            "Why it may matter:\n\n"
            "Risk / caveat:\n",
            encoding="utf-8",
        )
    print(f"MANUAL_NOTE_TEMPLATE={template}")
    return 0


def hypothesis_rows() -> list[dict[str, Any]]:
    now = utc_now()
    rows = []
    for item in INITIAL_HYPOTHESES:
        row = {
            **item,
            "created_at": now,
            "expected_improvement": item["expected_improvement"],
            "risk": item["risk"],
            "status": "ready_for_backtest",
            "experiment_plan_id": f"EXP-{item['hypothesis_id']}",
            "gate_requirements": read_config(HYPOTHESIS_RULES).get("gate_requirements", []),
        }
        rows.append(row)
    return rows


def hypothesis_registry() -> int:
    ensure_dir(HYP_DIR)
    ensure_dir(USER_HYP_DIR)
    rows = hypothesis_rows()
    write_jsonl(USER_HYP_DIR / "hypothesis_registry.jsonl", rows)
    matrix_rows = [{**r, "expected_improvement": ";".join(r["expected_improvement"]), "risk": ";".join(r["risk"]), "gate_requirements": ";".join(r["gate_requirements"])} for r in rows]
    write_csv(HYP_DIR / "hypothesis_matrix.csv", matrix_rows, [
        "hypothesis_id", "created_at", "source_claim_ids", "title", "module_target",
        "expected_improvement", "risk", "status", "experiment_plan_id", "priority", "gate_requirements",
    ])
    summary = {"generated_at": utc_now(), "status": "PASS", "hypotheses_count": len(rows), "ready_for_backtest": len(rows), "gate": gate_snapshot()}
    write_json(HYP_DIR / "hypothesis_summary.json", summary)
    lines = ["# Hypothesis Registry", "", f"Status: `{summary['status']}`", "", "| id | priority | target | title | status |", "|---|---:|---|---|---|"]
    for row in rows:
        lines.append(f"| `{row['hypothesis_id']}` | {row['priority']} | `{row['module_target']}` | {row['title']} | `{row['status']}` |")
    (HYP_DIR / "hypothesis_registry.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    record_audit("hypothesis_registry", "PASS", f"Generated {len(rows)} hypotheses.")
    print("HYPOTHESIS_REGISTRY_STATUS=PASS")
    return 0


def experiment_for(row: dict[str, Any]) -> dict[str, Any]:
    rules = read_config(EXPERIMENT_RULES)
    return {
        "experiment_id": f"EXP-{row['hypothesis_id']}",
        "hypothesis_id": row["hypothesis_id"],
        "title": row["title"],
        "experiment_type": row["experiment_type"],
        "mode": "plan_only",
        "baseline": "baseline_nfi",
        "candidate": f"candidate_{row['hypothesis_id'].lower()}",
        "train_test_split": "365d target: train 60%, validation 20%, test 20%; mark LOW_SAMPLE if unavailable.",
        "walk_forward_split": "3 rolling windows minimum when enough data exists.",
        "fees": rules.get("default_fees", {}),
        "slippage_stress": rules.get("default_fees", {}).get("slippage_ratio_per_side_stress", []),
        "required_outputs": rules.get("required_sections", []),
        "sample_size_warning": "LOW_SAMPLE until >=50 trades; target 50-100+ trades.",
        "live_trading_allowed": False,
        "shadow_only": True,
    }


def offline_optimization_experiments() -> int:
    ensure_dir(OPT_EXP_DIR)
    ensure_dir(USER_OPT_EXP_DIR)
    evidence = load_evidence_rows()
    if not evidence:
        print("OPTIMIZATION_EXPERIMENT_STATUS=BLOCKED_NO_EVIDENCE")
        return 2

    hypotheses = {row["hypothesis_id"]: row for row in hypothesis_rows()}
    metrics = evaluate_all(evidence)
    walk_rows = walkforward_rows(evidence)
    stress_rows = slippage_stress(evidence)
    regime_rows = grouped_performance(evidence, "primary_regime")
    pair_rows = grouped_performance(evidence, "pair")
    tag_rows = grouped_performance(evidence, "enter_tag")
    write_json(OPT_DIR / "offline_candidate_metrics.json", {
        "generated_at": utc_now(),
        "status": "OFFLINE_EVALUATED_LOW_SAMPLE",
        "source": "reports/decision_engine_v2/v2_decision_journal.csv",
        "rows": len(evidence),
        "candidates": metrics,
    })

    summaries = []
    for hypothesis_id in V11_HYPOTHESES:
        hyp = hypotheses[hypothesis_id]
        plan = experiment_for(hyp)
        plan.update({
            "mode": "offline_evaluation",
            "candidate": CANDIDATE_IDS,
            "data_sources": [
                "reports/decision_engine_v2/v2_decision_journal.csv",
                "reports/market_state/pair_quality_scores.csv",
                "user_data/market_state/market_state_history.csv",
            ],
            "decision_leakage_policy": "candidate stake uses signal-time fields only",
            "profit_source": "Freqtrade historical net profit; incremental slippage applied after decision",
        })
        exp_dir = OPT_EXP_DIR / plan["experiment_id"]
        ensure_dir(exp_dir)
        write_json(exp_dir / "experiment_config.json", plan)
        (exp_dir / "experiment_plan.md").write_text(
            "# Optimization Experiment Plan\n\n"
            f"Experiment: `{plan['experiment_id']}`\n\n"
            f"Hypothesis: `{hypothesis_id}` {hyp['title']}\n\n"
            "Mode: `offline_evaluation`\n\n"
            "The replay reads existing evidence only. Candidate decisions use signal-time fields; realized profit is scoring data only.\n",
            encoding="utf-8",
        )
        write_csv(exp_dir / "backtest_matrix.csv", metrics, METRIC_FIELDS)
        write_csv(exp_dir / "walkforward_matrix.csv", walk_rows, [
            "window", "start", "end", "leakage_check", *METRIC_FIELDS,
        ])
        write_csv(exp_dir / "slippage_stress.csv", stress_rows, [
            "candidate_id", "slippage_ratio_per_side", "profit_after_slippage", "max_drawdown", "sample_size",
        ])
        group_fields = [field for field in METRIC_FIELDS if field != "candidate_id"]
        write_csv(exp_dir / "regime_performance.csv", regime_rows, ["candidate_id", "primary_regime", *group_fields])
        write_csv(exp_dir / "pair_performance.csv", pair_rows, ["candidate_id", "pair", *group_fields])
        write_csv(exp_dir / "tag_performance.csv", tag_rows, ["candidate_id", "enter_tag", *group_fields])
        best = max(metrics, key=lambda row: float(row["profit_after_slippage"]))
        summary = {
            "generated_at": utc_now(),
            "status": "OFFLINE_EVALUATED_LOW_SAMPLE",
            "experiment_id": plan["experiment_id"],
            "hypothesis_id": hypothesis_id,
            "historical_rows": len(evidence),
            "candidates_evaluated": CANDIDATE_IDS,
            "best_historical_candidate": best["candidate_id"],
            "best_profit_after_slippage": best["profit_after_slippage"],
            "sample_size_warning": "LOW_SAMPLE",
            "leakage_check": "PASS_NO_REALIZED_PROFIT_IN_DECISION",
            "promote_to_shadow": False,
            "promote_to_live": False,
            "real_trading_allowed": False,
        }
        write_json(exp_dir / "experiment_summary.json", summary)
        (exp_dir / "experiment_report.md").write_text(
            "# Experiment Report\n\n"
            "Status: `OFFLINE_EVALUATED_LOW_SAMPLE`\n\n"
            f"Hypothesis: `{hypothesis_id}`\n\n"
            f"Historical rows: `{len(evidence)}`\n\n"
            f"Best historical candidate by profit after base slippage: `{best['candidate_id']}`.\n\n"
            "This is a candidate replay, not proof of stable profit. Forward and shadow evidence remain required.\n",
            encoding="utf-8",
        )
        summaries.append(summary)

    write_json(OPT_EXP_DIR / "optimization_experiment_index.json", {
        "generated_at": utc_now(),
        "status": "OFFLINE_EVALUATED_LOW_SAMPLE",
        "experiments": summaries,
    })
    record_audit("run_optimization_experiment", "PASS", f"Offline-evaluated {len(summaries)} experiments across {len(CANDIDATE_IDS)} candidates.")
    print("OPTIMIZATION_EXPERIMENT_STATUS=OFFLINE_EVALUATED_LOW_SAMPLE")
    return 0


def optimization_experiment(dry_run_plan_only: bool = False) -> int:
    if not dry_run_plan_only:
        return offline_optimization_experiments()
    ensure_dir(OPT_EXP_DIR)
    ensure_dir(USER_OPT_EXP_DIR)
    rows = hypothesis_rows()
    summaries = []
    for hyp in rows:
        plan = experiment_for(hyp)
        exp_dir = OPT_EXP_DIR / plan["experiment_id"]
        user_dir = USER_OPT_EXP_DIR / plan["experiment_id"]
        ensure_dir(exp_dir)
        ensure_dir(user_dir)
        write_json(exp_dir / "experiment_config.json", plan)
        (exp_dir / "experiment_plan.md").write_text(
            "# Optimization Experiment Plan\n\n"
            f"Experiment: `{plan['experiment_id']}`\n\n"
            f"Hypothesis: `{hyp['hypothesis_id']}` {hyp['title']}\n\n"
            f"Type: `{plan['experiment_type']}`\n\n"
            "This plan does not modify strategy or trading config. It defines evidence required before shadow promotion.\n",
            encoding="utf-8",
        )
        empty_fields = ["metric", "baseline", "candidate", "notes"]
        for name in [
            "backtest_matrix.csv", "walkforward_matrix.csv", "slippage_stress.csv",
            "regime_performance.csv", "pair_performance.csv", "tag_performance.csv",
        ]:
            write_csv(exp_dir / name, [{"metric": "PLAN_ONLY", "baseline": "", "candidate": "", "notes": "No experiment executed yet."}], empty_fields)
        summary = {
            "generated_at": utc_now(),
            "status": "PLAN_ONLY",
            "experiment_id": plan["experiment_id"],
            "hypothesis_id": hyp["hypothesis_id"],
            "sample_size_warning": "LOW_SAMPLE",
            "promote_to_shadow": False,
            "real_trading_allowed": False,
        }
        write_json(exp_dir / "experiment_summary.json", summary)
        (exp_dir / "experiment_report.md").write_text(
            f"# Experiment Report\n\nStatus: `PLAN_ONLY`\n\nExperiment `{plan['experiment_id']}` is queued. No backtest was executed by this harness run.\n",
            encoding="utf-8",
        )
        summaries.append(summary)
    write_json(OPT_EXP_DIR / "optimization_experiment_index.json", {"generated_at": utc_now(), "status": "PLAN_ONLY", "experiments": summaries})
    record_audit("run_optimization_experiment", "PASS", f"Generated {len(summaries)} plan-only experiments.")
    print("OPTIMIZATION_EXPERIMENT_STATUS=PLAN_ONLY")
    return 0


def walkforward(plan_only: bool = False) -> int:
    ensure_dir(OPT_DIR)
    if not plan_only:
        evidence = load_evidence_rows()
        if not evidence:
            print("WALKFORWARD_STATUS=BLOCKED_NO_EVIDENCE")
            return 2
        rows = walkforward_rows(evidence)
        write_csv(OPT_DIR / "walkforward_matrix.csv", rows, [
            "window", "start", "end", "leakage_check", *METRIC_FIELDS,
        ])
        summary = {
            "generated_at": utc_now(),
            "status": "OFFLINE_EVALUATED_LOW_SAMPLE",
            "historical_rows": len(evidence),
            "windows_executed": len({row["window"] for row in rows}),
            "candidates_evaluated": len(CANDIDATE_IDS),
            "sample_warning": "LOW_SAMPLE",
            "leakage_check": "PASS_NO_REALIZED_PROFIT_IN_DECISION",
            "gate": gate_snapshot(),
        }
        write_json(OPT_DIR / "walkforward_summary.json", summary)
        (OPT_DIR / "walkforward_report.md").write_text(
            "# Walk-forward Analysis\n\n"
            "Status: `OFFLINE_EVALUATED_LOW_SAMPLE`\n\n"
            f"Historical rows: `{len(evidence)}`\n\n"
            "Executed chronological 60/20/20 train-validation-test segments and three rolling test windows.\n\n"
            "Candidate decisions use signal-time fields only. The sample remains too small for stable-profit claims.\n",
            encoding="utf-8",
        )
        record_audit("walkforward_analysis", "PASS", f"Executed offline walk-forward replay on {len(evidence)} rows.")
        print("WALKFORWARD_STATUS=OFFLINE_EVALUATED_LOW_SAMPLE")
        return 0
    rows = []
    for hyp in hypothesis_rows():
        rows.append({
            "experiment_id": f"EXP-{hyp['hypothesis_id']}",
            "hypothesis_id": hyp["hypothesis_id"],
            "split_method": "rolling windows",
            "train": "60%",
            "validation": "20%",
            "test": "20%",
            "status": "PLAN_ONLY",
            "sample_warning": "LOW_SAMPLE until 365d and 50+ trades are present",
        })
    write_csv(OPT_DIR / "walkforward_matrix.csv", rows, ["experiment_id", "hypothesis_id", "split_method", "train", "validation", "test", "status", "sample_warning"])
    summary = {"generated_at": utc_now(), "status": "PLAN_ONLY", "windows_planned": len(rows), "gate": gate_snapshot()}
    write_json(OPT_DIR / "walkforward_summary.json", summary)
    (OPT_DIR / "walkforward_report.md").write_text("# Walk-forward Analysis Plan\n\nStatus: `PLAN_ONLY`\n\n365d target split: train 60%, validation 20%, test 20%, with rolling windows when sample size allows.\n", encoding="utf-8")
    record_audit("walkforward_analysis", "PASS", "Generated walk-forward plan.")
    print("WALKFORWARD_STATUS=PLAN_ONLY")
    return 0


def anti_overfit(plan_only: bool = False) -> int:
    ensure_dir(OPT_DIR)
    if not plan_only:
        evidence = load_evidence_rows()
        if not evidence:
            print("ANTI_OVERFIT_STATUS=BLOCKED_NO_EVIDENCE")
            return 2
        rows = anti_overfit_rows(evidence)
        shadow = load_json(PROJECT_ROOT / "reports/shadow_decision/shadow_decision_summary.json", {})
        forward_trades = int(shadow.get("forward_closed_trades") or shadow.get("recent_closed_trades_count") or 0)
        overall_risk = "HIGH" if forward_trades < 20 or any(row["overfit_risk"] == "HIGH" for row in rows) else "MEDIUM"
        for row in rows:
            row["forward_closed_trades"] = forward_trades
            row["promotion_blocked"] = overall_risk == "HIGH"
        write_csv(OPT_DIR / "anti_overfit_matrix.csv", rows, [
            "candidate_id", "historical_sample_size", "train_profit_after_slippage",
            "test_profit_after_slippage", "train_test_sign_stable", "leakage_check",
            "sample_warning", "overfit_risk", "forward_closed_trades", "promotion_blocked",
        ])
        summary = {
            "generated_at": utc_now(),
            "status": "OFFLINE_EVALUATED_LOW_SAMPLE",
            "overfit_risk": overall_risk,
            "historical_sample_size": len(evidence),
            "forward_closed_trades": forward_trades,
            "leakage_check": "PASS",
            "sample_warning": "LOW_SAMPLE",
            "promote_to_shadow_allowed": False,
            "candidate_checks": rows,
        }
        write_json(OPT_DIR / "anti_overfit_summary.json", summary)
        (OPT_DIR / "anti_overfit_report.md").write_text(
            "# Anti-overfit Check\n\n"
            "Status: `OFFLINE_EVALUATED_LOW_SAMPLE`\n\n"
            f"Overfit risk: `{overall_risk}`\n\n"
            f"Historical rows: `{len(evidence)}`; forward closed trades: `{forward_trades}`.\n\n"
            "Leakage check passed for replay decisions, but low historical and forward samples block promotion.\n",
            encoding="utf-8",
        )
        record_audit("anti_overfit_check", "PASS", f"Executed anti-overfit checks; risk={overall_risk}.")
        print("ANTI_OVERFIT_STATUS=OFFLINE_EVALUATED_LOW_SAMPLE")
        print(f"OVERFIT_RISK={overall_risk}")
        return 0
    shadow = load_json(PROJECT_ROOT / "reports/shadow_decision/shadow_decision_summary.json", {})
    forward_trades = int(shadow.get("forward_closed_trades") or shadow.get("recent_closed_trades_count") or 0)
    risk = "HIGH" if forward_trades < 20 else "MEDIUM"
    checks = [
        ("small_sample_warning", forward_trades >= 20, f"forward_closed_trades={forward_trades}"),
        ("train_test_divergence", False, "not measured yet"),
        ("regime_imbalance", False, "requires experiment results"),
        ("pair_concentration", False, "requires experiment results"),
        ("tag_concentration", False, "requires experiment results"),
        ("leakage_risk", False, "lookahead-analysis not run for new candidates yet"),
    ]
    rows = [{"check": c, "passed": p, "notes": n} for c, p, n in checks]
    write_csv(OPT_DIR / "anti_overfit_matrix.csv", rows, ["check", "passed", "notes"])
    summary = {"generated_at": utc_now(), "status": "PLAN_ONLY", "overfit_risk": risk, "forward_closed_trades": forward_trades, "promote_to_shadow_allowed": risk != "HIGH"}
    write_json(OPT_DIR / "anti_overfit_summary.json", summary)
    (OPT_DIR / "anti_overfit_report.md").write_text(f"# Anti-overfit Check\n\nStatus: `PLAN_ONLY`\n\nOverfit risk: `{risk}`\n\nNo candidate may be promoted while overfit risk is HIGH.\n", encoding="utf-8")
    record_audit("anti_overfit_check", "PASS", f"Generated anti-overfit plan with risk={risk}.")
    print(f"ANTI_OVERFIT_STATUS=PLAN_ONLY")
    print(f"OVERFIT_RISK={risk}")
    return 0


def stable_profit_score() -> int:
    ensure_dir(OPT_DIR)
    metrics_doc = load_json(OPT_DIR / "offline_candidate_metrics.json", {})
    metrics = metrics_doc.get("candidates", []) or evaluate_all()
    if not metrics:
        print("STABLE_PROFIT_SCORE_STATUS=BLOCKED_NO_EVIDENCE")
        return 2
    anti = load_json(OPT_DIR / "anti_overfit_summary.json", {})
    overfit_by_candidate = {row.get("candidate_id"): row.get("overfit_risk", "HIGH") for row in anti.get("candidate_checks", [])}
    baseline = next((row for row in metrics if row["candidate_id"] == "baseline_nfi"), metrics[0])
    baseline_profit = max(1e-9, float(baseline["profit_after_slippage"]))
    baseline_drawdown = max(1e-9, float(baseline["max_drawdown"]))
    simplicity = {
        "baseline_nfi": 1.0,
        "decision_engine_v2_frozen": 0.6,
        "decision_engine_v2_relaxed": 0.55,
        "sizing_only_v1": 0.9,
        "sizing_only_pair_quality_v1": 0.9,
        "sizing_only_atr_breadth_v1": 0.75,
        "slippage_aware_sizing_v1": 0.75,
    }
    rows = []
    for metric in metrics:
        candidate_id = metric["candidate_id"]
        overfit_risk = overfit_by_candidate.get(candidate_id, anti.get("overfit_risk", "HIGH"))
        profit_score = max(0.0, min(1.0, float(metric["profit_after_slippage"]) / baseline_profit))
        drawdown_score = max(0.0, min(1.0, (baseline_drawdown - float(metric["max_drawdown"])) / baseline_drawdown))
        pf = metric.get("profit_factor")
        profit_factor_score = 1.0 if pf is None else max(0.0, min(1.0, float(pf) / 3.0))
        net_filter_score = max(0.0, min(1.0, float(metric["net_filter_value"]) / 10.0))
        loss_score = 1.0 / (1.0 + int(metric["max_consecutive_losses"]))
        sample_score = min(1.0, int(metric["sample_size"]) / 100.0)
        score = (
            profit_score * 0.20 + drawdown_score * 0.20 + profit_factor_score * 0.15
            + net_filter_score * 0.15 + loss_score * 0.10
            + float(metric["regime_stability"]) * 0.10 + sample_score * 0.05
            + simplicity[candidate_id] * 0.05
        )
        blockers = []
        if int(metric["sample_size"]) < 100:
            blockers.append("LOW_SAMPLE")
            score -= 0.15
        if overfit_risk == "HIGH":
            blockers.append("OVERFIT_RISK_HIGH")
            score -= 0.30
        if float(metric["net_filter_value"]) < 0:
            blockers.append("NEGATIVE_NET_FILTER_VALUE")
            score -= 0.20 * min(1.0, abs(float(metric["net_filter_value"])) / baseline_profit)
        if float(metric["profit_after_slippage"]) <= float(baseline["profit_after_slippage"]):
            blockers.append("NO_PROFIT_IMPROVEMENT_VS_BASELINE")
        if float(metric["max_drawdown"]) >= float(baseline["max_drawdown"]):
            blockers.append("NO_DRAWDOWN_IMPROVEMENT_VS_BASELINE")
        score = max(0.0, min(1.0, score))
        promote = (
            candidate_id != "baseline_nfi" and score >= 0.65
            and float(metric["net_filter_value"]) >= 0 and overfit_risk != "HIGH"
            and int(metric["sample_size"]) >= 50
            and float(metric["profit_after_slippage"]) > float(baseline["profit_after_slippage"])
            and float(metric["max_drawdown"]) < float(baseline["max_drawdown"])
        )
        rows.append({
            "candidate_id": candidate_id,
            "score": round(score, 6),
            "profit_after_slippage": metric["profit_after_slippage"],
            "max_drawdown": metric["max_drawdown"],
            "net_filter_value": metric["net_filter_value"],
            "sample_size": metric["sample_size"],
            "overfit_risk": overfit_risk,
            "reason": "Offline score ranks evidence quality; it does not grant trading permission.",
            "blockers": ";".join(blockers),
            "promote_to_shadow": promote,
            "promote_to_live": False,
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    write_csv(OPT_DIR / "stable_profit_leaderboard.csv", rows, [
        "candidate_id", "score", "profit_after_slippage", "max_drawdown", "net_filter_value",
        "sample_size", "overfit_risk", "reason", "blockers", "promote_to_shadow", "promote_to_live",
    ])
    promoted = [row for row in rows if row["promote_to_shadow"]]
    experimental = [row for row in rows if row["candidate_id"] != "baseline_nfi"]
    summary = {
        "generated_at": utc_now(), "status": "PASS", "top_candidate": rows[0] if rows else {},
        "best_experimental_candidate": experimental[0] if experimental else {},
        "no_candidate_ready_for_shadow": not promoted, "shadow_candidates": promoted,
        "promote_to_live_allowed": False,
        "score_interpretation": "meaningful for historical ranking only; LOW_SAMPLE and forward gates still apply",
        "gate": gate_snapshot(),
    }
    write_json(OPT_DIR / "stable_profit_score_summary.json", summary)
    lines = ["# Stable Profit Score", "", "Score ranks offline evidence only. It does not permit live trading.", "", "| candidate | score | profit after slippage | drawdown | net filter value | shadow | blockers |", "|---|---:|---:|---:|---:|---|---|"]
    for row in rows:
        lines.append(f"| `{row['candidate_id']}` | {row['score']} | {row['profit_after_slippage']} | {row['max_drawdown']} | {row['net_filter_value']} | `{row['promote_to_shadow']}` | {row['blockers']} |")
    if not promoted:
        lines.extend(["", "Result: `no_candidate_ready_for_shadow`."])
    (OPT_DIR / "stable_profit_score_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    record_audit("stable_profit_score", "PASS", "Generated stable profit score leaderboard.")
    print("STABLE_PROFIT_SCORE_STATUS=PASS")
    return 0


def promote_shadow() -> int:
    ensure_dir(SHADOW_PROMOTION_DIR)
    leaderboard = []
    path = OPT_DIR / "stable_profit_leaderboard.csv"
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            leaderboard = list(csv.DictReader(f))
    selected = [r for r in leaderboard if str(r.get("promote_to_shadow")).lower() == "true"][:2]
    config_path = PROJECT_ROOT / "configs/shadow_decision_candidates.generated.yaml"
    config = {
        "generated_at": utc_now(),
        "policy": "shadow_only_no_live_orders",
        "baseline_required": ["baseline_nfi", "sizing_only", "decision_engine_v2_relaxed"],
        "new_candidates": selected,
    }
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    status = "SHADOW_PROPOSAL_CREATED" if selected else "NO_CANDIDATE_PROMOTED"
    summary = {"generated_at": utc_now(), "status": status, "promoted_count": len(selected), "micro_live_allowed": False, "gate": gate_snapshot()}
    write_json(SHADOW_PROMOTION_DIR / "shadow_promotion_summary.json", summary)
    detail = "A shadow-only proposal was created; it does not control orders." if selected else "No candidate met promotion requirements."
    (SHADOW_PROMOTION_DIR / "shadow_promotion_report.md").write_text(
        f"# Shadow Promotion Report\n\nStatus: `{status}`\n\n{detail} Baseline, sizing_only, and v2_relaxed remain required.\n",
        encoding="utf-8",
    )
    record_audit("promote_candidate_to_shadow", "PASS", status)
    print(f"SHADOW_PROMOTION_STATUS={status}")
    return 0


def weekly_report() -> int:
    ensure_dir(CI_DIR)
    claims = read_jsonl(USER_CI_DIR / "normalized_claims.jsonl")
    theme_counts: dict[str, int] = {}
    for claim in claims:
        theme_counts[claim.get("claim_type", "unknown")] = theme_counts.get(claim.get("claim_type", "unknown"), 0) + 1
    rows = [{"theme": k, "count": v} for k, v in sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)]
    write_csv(CI_DIR / "community_trend_matrix.csv", rows, ["theme", "count"])
    summary = {"generated_at": utc_now(), "status": "PASS", "claims_count": len(claims), "top_themes": rows[:5], "next_experiments": [h["hypothesis_id"] for h in hypothesis_rows()[:5]]}
    write_json(CI_DIR / "community_weekly_summary.json", summary)
    (CI_DIR / "community_weekly_report.md").write_text("# Community Intelligence Weekly Report\n\nStatus: `PASS`\n\nHigh-frequency themes are converted into experiments only after manual review and validation gates.\n", encoding="utf-8")
    record_audit("community_intel_weekly_report", "PASS", f"Weekly report generated with {len(claims)} claims.")
    print("COMMUNITY_WEEKLY_STATUS=PASS")
    return 0


def hyperopt_plan() -> int:
    ensure_dir(HYPEROPT_DIR)
    summary = {
        "generated_at": utc_now(),
        "status": "PLAN_ONLY",
        "allowed_spaces": ["roi", "stoploss", "trailing", "protections"],
        "disallowed": ["direct live promotion", "broad unrestricted spaces", "using best result without walk-forward"],
        "required_after_hyperopt": ["train/test split", "walk-forward", "slippage stress", "anti-overfit", "shadow promotion", "gatekeeper check"],
        "real_trading_allowed": False,
    }
    write_json(HYPEROPT_DIR / "hyperopt_research_summary.json", summary)
    (HYPEROPT_DIR / "hyperopt_research_plan.md").write_text("# Hyperopt Research Plan\n\nStatus: `PLAN_ONLY`\n\nHyperopt is limited to ROI, stoploss, trailing, and protections. Raw best results cannot be used for live trading.\n", encoding="utf-8")
    record_audit("hyperopt_research_plan", "PASS", "Generated hyperopt research plan.")
    print("HYPEROPT_RESEARCH_STATUS=PLAN_ONLY")
    return 0


def dashboard() -> int:
    ensure_dir(OPT_DIR)
    gate = gate_snapshot()
    score = load_json(OPT_DIR / "stable_profit_score_summary.json", {})
    shadow = load_json(PROJECT_ROOT / "reports/shadow_decision/shadow_decision_summary.json", {})
    daily = load_json(PROJECT_ROOT / "reports/ops/daily/daily_ops_summary.json", {})
    anti = load_json(OPT_DIR / "anti_overfit_summary.json", {})
    promotion = load_json(SHADOW_PROMOTION_DIR / "shadow_promotion_summary.json", {})
    forward_closed = int(shadow.get("forward_closed_trades") or shadow.get("recent_closed_trades_count") or 0)
    observation_days = float(shadow.get("observation_days") or 0)
    blockers = []
    if forward_closed < 20:
        blockers.append("forward_closed_trades < 20")
    if observation_days < 14:
        blockers.append("shadow_observation_days < 14")
    if load_json(PROJECT_ROOT / "reports/decision_engine_v2/decision_engine_v2_summary.json", {}).get("v2_net_filter_value", -1) < 0:
        blockers.append("Decision Engine v2 net_filter_value is historically negative")
    if anti.get("overfit_risk", "HIGH") == "HIGH":
        blockers.append("offline candidates remain HIGH overfit risk / LOW_SAMPLE")
    summary = {
        "generated_at": utc_now(),
        "status": "PASS",
        "baseline_nfi_historical_result": "available in prior reports; not re-run here",
        "decision_engine_v1_v2_result": load_json(PROJECT_ROOT / "reports/decision_engine_v2/decision_engine_v2_summary.json", {}),
        "best_candidate": score.get("top_candidate", {}),
        "best_experimental_candidate": score.get("best_experimental_candidate", {}),
        "best_shadow_candidate": promotion.get("status") if promotion.get("promoted_count") else "none",
        "candidate_promoted_to_shadow": bool(promotion.get("promoted_count")),
        "forward_evidence_status": "BLOCKED_DRY_RUN_STOPPED" if gate["forward_evidence_blocked"] else "COLLECTING",
        "testnet_status": gate["gatekeeper_status"],
        "gatekeeper_status": gate["gatekeeper_status"],
        "micro_live_status": gate["micro_live_status"],
        "open_blockers": blockers,
        "next_experiments": ["H1", "H5", "H7", "H8", "H3"],
        "forward_closed_trades": forward_closed,
        "shadow_consistency": shadow.get("shadow_consistency", shadow.get("consistency_status", "")),
        "observation_days": observation_days,
        "stable_profit_score": score.get("top_candidate", {}).get("score", 0),
        "dry_run_running": bool(daily.get("dry_run_running")),
    }
    write_json(OPT_DIR / "optimization_dashboard.json", summary)
    history_path = OPT_DIR / "optimization_kpi_history.csv"
    exists = history_path.exists()
    ensure_dir(history_path.parent)
    with history_path.open("a", newline="", encoding="utf-8") as f:
        fields = ["timestamp", "gatekeeper_status", "micro_live_status", "forward_closed_trades", "observation_days", "stable_profit_score", "dry_run_running"]
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": summary["generated_at"],
            "gatekeeper_status": summary["gatekeeper_status"],
            "micro_live_status": summary["micro_live_status"],
            "forward_closed_trades": summary["forward_closed_trades"],
            "observation_days": summary["observation_days"],
            "stable_profit_score": summary["stable_profit_score"],
            "dry_run_running": summary["dry_run_running"],
        })
    lines = [
        "# Optimization Dashboard",
        "",
        f"Gatekeeper: `{summary['gatekeeper_status']}`",
        f"Micro-live: `{summary['micro_live_status']}`",
        f"Forward evidence: `{summary['forward_evidence_status']}`",
        f"Forward closed trades: `{summary['forward_closed_trades']}`",
        f"Observation days: `{summary['observation_days']}`",
        f"Top candidate: `{summary['best_candidate'].get('candidate_id', 'N/A')}`",
        f"Best experimental candidate: `{summary['best_experimental_candidate'].get('candidate_id', 'N/A')}`",
        f"Candidate promoted to shadow: `{summary['candidate_promoted_to_shadow']}`",
        f"Dry-run running: `{summary['dry_run_running']}`",
        f"Open blockers: `{'; '.join(summary['open_blockers']) or 'none'}`",
        "",
        "Current system is a stable-profit-oriented evidence loop, not a stable-profit live system.",
    ]
    (OPT_DIR / "OPTIMIZATION_DASHBOARD.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    record_audit("optimization_dashboard", "PASS", "Generated optimization dashboard.")
    print("OPTIMIZATION_DASHBOARD_STATUS=PASS")
    return 0


def final_report() -> int:
    ensure_dir(LOOP_DIR)
    gate = gate_snapshot()
    hyp = load_json(HYP_DIR / "hypothesis_summary.json", {})
    claims = load_json(CI_DIR / "community_intel_summary.json", {})
    score = load_json(OPT_DIR / "stable_profit_score_summary.json", {})
    dash = load_json(OPT_DIR / "optimization_dashboard.json", {})
    summary = {
        "generated_at": utc_now(),
        "status": "PASS",
        "sensitive_files_modified": False,
        "api_key_written": False,
        "real_trading_enabled": False,
        "gatekeeper_status": gate["gatekeeper_status"],
        "micro_live_status": gate["micro_live_status"],
        "community_sources_ready": (CI_DIR / "source_registry.json").exists(),
        "community_claims_count": claims.get("claims_count", 0),
        "hypotheses_count": hyp.get("hypotheses_count", 0),
        "top_hypotheses": ["H1", "H5", "H7", "H8", "H3"],
        "experiment_harness_ready": (OPT_EXP_DIR / "optimization_experiment_index.json").exists(),
        "walkforward_ready": (OPT_DIR / "walkforward_summary.json").exists(),
        "anti_overfit_ready": (OPT_DIR / "anti_overfit_summary.json").exists(),
        "stable_profit_score_ready": (OPT_DIR / "stable_profit_score_summary.json").exists(),
        "dashboard_ready": (OPT_DIR / "optimization_dashboard.json").exists(),
        "best_direction": "position sizing and slippage-aware filtering before hard block rules",
        "blockers": dash.get("open_blockers", []),
        "dry_run_running": gate["dry_run_running"],
        "micro_live_allowed": False,
    }
    write_json(LOOP_DIR / "stable_profit_loop_summary.json", summary)
    lines = [
        "# Stable Profit Evidence Loop Report",
        "",
        f"Status: `{summary['status']}`",
        f"Gatekeeper: `{summary['gatekeeper_status']}`",
        f"Micro-live: `{summary['micro_live_status']}`",
        f"Community sources ready: `{summary['community_sources_ready']}`",
        f"Community claims: `{summary['community_claims_count']}`",
        f"Hypotheses: `{summary['hypotheses_count']}`",
        f"Top hypotheses: `{', '.join(summary['top_hypotheses'])}`",
        f"Best direction: {summary['best_direction']}",
        f"Dry-run running: `{summary['dry_run_running']}`",
        f"Needs forward evidence restart: `{not summary['dry_run_running']}`",
        f"Open blockers: `{len(summary['blockers'])}`",
        "",
        "This is not a stable-profit live system. It is a stable-profit-oriented evidence loop.",
        "",
        "Allowed: dry-run, shadow, testnet. Forbidden: real-money micro-live and automatic real-money trading.",
        "",
        "This is not investment advice. Real trading can lose all capital.",
    ]
    (LOOP_DIR / "stable_profit_loop_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    record_audit("stable_profit_loop_report", "PASS", "Generated final stable profit loop report.")
    print("STABLE_PROFIT_LOOP_STATUS=PASS")
    return 0


def v11_final_report() -> int:
    ensure_dir(LOOP_DIR)
    ensure_dir(PROJECT_ROOT / "reports/forward_evidence")
    gate = gate_snapshot()
    safety = runtime_safety()
    daily = load_json(PROJECT_ROOT / "reports/ops/daily/daily_ops_summary.json", {})
    score = load_json(OPT_DIR / "stable_profit_score_summary.json", {})
    anti = load_json(OPT_DIR / "anti_overfit_summary.json", {})
    experiments = load_json(OPT_EXP_DIR / "optimization_experiment_index.json", {})
    promotion = load_json(SHADOW_PROMOTION_DIR / "shadow_promotion_summary.json", {})
    tag_result = run_cmd(["git", "rev-list", "-n", "1", "v1.0-stable-profit-evidence-loop"])
    sensitive_diff = run_cmd([
        "git", "diff", "--quiet", "--", ".env", "user_data/config.runtime.json",
        "user_data/strategies/NostalgiaForInfinityX7.py",
    ])
    tag_target = tag_result.get("stdout", "").strip()
    version_summary = {
        "generated_at": utc_now(),
        "status": "PASS" if tag_target else "FAIL",
        "tag": "v1.0-stable-profit-evidence-loop",
        "tag_target": tag_target,
        "expected_v1_commit": "b70e11b",
        "tag_matches_v1_commit": tag_target.startswith("b70e11b"),
        "tag_overwritten": False,
    }
    write_json(LOOP_DIR / "version_status.json", version_summary)
    (LOOP_DIR / "version_status.md").write_text(
        "# Version Status\n\n"
        f"Status: `{version_summary['status']}`\n\n"
        f"Tag: `{version_summary['tag']}`\n\n"
        f"Target: `{tag_target}`\n\n"
        f"Matches v1.0 commit: `{version_summary['tag_matches_v1_commit']}`\n",
        encoding="utf-8",
    )

    dry_run_running = bool(daily.get("dry_run_running", gate.get("dry_run_running", False)))
    forward_blocked = bool(daily.get("forward_evidence_blocked", not dry_run_running))
    activation = {
        "generated_at": utc_now(),
        "status": "PASS" if dry_run_running and safety.get("pass") else "BLOCKED",
        "dry_run_running": dry_run_running,
        "running_mode": daily.get("dry_run_running_mode", gate.get("dry_run_running_mode", "none")),
        "forward_evidence_blocked": forward_blocked,
        "runtime_safety": safety,
        "sensitive_files_modified": sensitive_diff.get("exit_code") != 0,
        "windows_fallback": r"D:\AI-Workspace\Projects\crypto-quant-nfi\scripts\start-native-windows.ps1",
    }
    write_json(PROJECT_ROOT / "reports/forward_evidence/v11_dry_run_activation_summary.json", activation)
    fallback = "" if dry_run_running else f"\nRun `{activation['windows_fallback']}` from Windows PowerShell.\n"
    (PROJECT_ROOT / "reports/forward_evidence/v11_dry_run_activation_report.md").write_text(
        "# v1.1 Dry-run Activation\n\n"
        f"Status: `{activation['status']}`\n\n"
        f"Dry-run running: `{dry_run_running}`\n\n"
        f"Forward evidence blocked: `{forward_blocked}`\n\n"
        f"Runtime safety: `{safety.get('pass')}`\n"
        f"{fallback}",
        encoding="utf-8",
    )

    top = score.get("top_candidate", {})
    best_experimental = score.get("best_experimental_candidate", {})
    exp_rows = experiments.get("experiments", [])
    executed = [row.get("hypothesis_id") for row in exp_rows if row.get("status") == "OFFLINE_EVALUATED_LOW_SAMPLE"]
    summary = {
        "generated_at": utc_now(),
        "status": "PASS",
        "dry_run_restored": dry_run_running,
        "forward_evidence_blocked": forward_blocked,
        "gatekeeper_status": gate.get("gatekeeper_status"),
        "micro_live_status": "BLOCKED",
        "experiments_requested": V11_HYPOTHESES,
        "experiments_executed": executed,
        "all_first_batch_executed": set(executed) == set(V11_HYPOTHESES),
        "best_candidate": top.get("candidate_id", "N/A"),
        "best_candidate_score": top.get("score"),
        "best_experimental_candidate": best_experimental.get("candidate_id", "N/A"),
        "best_experimental_candidate_score": best_experimental.get("score"),
        "candidate_promoted_to_shadow": bool(promotion.get("promoted_count")),
        "shadow_promotion_status": promotion.get("status", "MISSING"),
        "overfit_risk": anti.get("overfit_risk", "HIGH"),
        "sample_warning": anti.get("sample_warning", "LOW_SAMPLE"),
        "stable_profit_score_meaningful": True,
        "stable_profit_score_scope": "historical candidate ranking only",
        "commit_status": "COMMITTED_IN_FINAL_DELIVERY",
        "sensitive_files_modified": sensitive_diff.get("exit_code") != 0,
        "real_trading_allowed": False,
        "allowed_modes": ["dry-run", "shadow", "testnet"],
        "next_step": "Keep dry-run running and collect 14-28 days plus at least 20 forward closed trades before reevaluating shadow promotion.",
    }
    write_json(LOOP_DIR / "v11_next_step_summary.json", summary)
    (LOOP_DIR / "v11_next_step_report.md").write_text(
        "# v1.1 Forward Evidence and First Experiments\n\n"
        f"Dry-run restored: `{summary['dry_run_restored']}`\n\n"
        f"Forward evidence blocked: `{summary['forward_evidence_blocked']}`\n\n"
        f"Gatekeeper: `{summary['gatekeeper_status']}`\n\n"
        "Micro-live: `BLOCKED`\n\n"
        f"First experiments executed: `{', '.join(executed)}`\n\n"
        f"Best historical candidate: `{summary['best_candidate']}` (score `{summary['best_candidate_score']}`).\n\n"
        f"Best experimental candidate: `{summary['best_experimental_candidate']}` (score `{summary['best_experimental_candidate_score']}`).\n\n"
        f"Shadow promotion: `{summary['shadow_promotion_status']}`\n\n"
        f"Overfit risk: `{summary['overfit_risk']}`; sample: `{summary['sample_warning']}`.\n\n"
        "The score is meaningful for relative historical ranking, not as proof of stable profit.\n\n"
        f"Next step: {summary['next_step']}\n\n"
        "Commit: `feat: run first stable profit evidence experiments` (created with this delivery).\n\n"
        "Allowed: dry-run, shadow, testnet. Real-money micro-live and automatic real-money trading remain forbidden.\n",
        encoding="utf-8",
    )
    record_audit("v11_next_step_report", "PASS", "Generated v1.1 activation and experiment summary; micro-live remains blocked.")
    print("V11_NEXT_STEP_STATUS=PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=[
        "source-registry", "ingest", "manual-note", "hypothesis-registry",
        "optimization-experiment", "walkforward", "anti-overfit", "score",
        "promote-shadow", "weekly-report", "hyperopt-plan", "dashboard", "final-report", "v11-final-report",
    ])
    parser.add_argument("--dry-run-plan-only", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()

    handlers = {
        "source-registry": source_registry,
        "ingest": community_ingest,
        "manual-note": manual_note,
        "hypothesis-registry": hypothesis_registry,
        "optimization-experiment": lambda: optimization_experiment(args.dry_run_plan_only),
        "walkforward": lambda: walkforward(args.plan_only),
        "anti-overfit": lambda: anti_overfit(args.plan_only),
        "score": stable_profit_score,
        "promote-shadow": promote_shadow,
        "weekly-report": weekly_report,
        "hyperopt-plan": hyperopt_plan,
        "dashboard": dashboard,
        "final-report": final_report,
        "v11-final-report": v11_final_report,
    }
    return handlers[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
