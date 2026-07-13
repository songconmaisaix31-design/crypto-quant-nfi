# Stable Profit Evidence Loop Spec

## Objective

Create a stable-profit-oriented evidence loop for the existing Freqtrade dry-run/testnet project.

This system does not modify the original strategy, does not enable live trading, and does not promote any candidate to real-money trading. It turns official documentation, compliant community notes, and internal reports into auditable claims, hypotheses, experiment plans, scoring, and shadow-only promotion candidates.

## Safety Constraints

- Keep main runtime `dry_run=True`.
- Keep `trading_mode=spot`.
- Keep `margin_mode=""`.
- Keep `can_short=False`.
- Do not modify `.env`.
- Do not modify `user_data/config.runtime.json`.
- Do not modify the original strategy file.
- Do not write or print API keys, secrets, passwords, or tokens.
- Do not enable futures, margin, leverage, shorting, fapi, dapi, or sapi trading paths.
- Keep micro-live blocked unless Gatekeeper explicitly outputs `MANUAL_MICRO_LIVE_ALLOWED`.

## Scope

- Community Intelligence Source Registry
- Community Intelligence Ingestion
- Manual note ingestion template
- Hypothesis Registry
- Optimization Experiment Harness
- Walk-forward Plan
- Anti-overfit Plan
- Stable Profit Score
- Shadow Promotion Pipeline
- Community Weekly Report
- Optimization Dashboard
- Hyperopt Research Plan
- Stable Profit Loop Final Report

## Acceptance Criteria

- All requested scripts run without requiring live credentials.
- Missing manual community notes produce `NO_COMMUNITY_NOTES_YET` and do not fail.
- Experiment harness supports `--dry-run-plan-only`.
- Walk-forward and anti-overfit support `--plan-only`.
- Gatekeeper remains below live permission.
- Secret scan and audit verify pass.
- Evidence Index includes the new modules.
- PROJECT_STATUS includes a Stable Profit Evidence Loop section.

## v1.1 Offline Evaluation

The v1.1 harness replays the existing 365-day historical decision journal. It
does not call an exchange and does not alter Freqtrade behavior. Candidate
stake multipliers use only information available at signal time; realized
profit is used only after the decision to score the result.

Required candidates are `baseline_nfi`, `decision_engine_v2_frozen`,
`decision_engine_v2_relaxed`, `sizing_only_v1`,
`sizing_only_pair_quality_v1`, `sizing_only_atr_breadth_v1`, and
`slippage_aware_sizing_v1`.

The evaluation must:

- use the existing strategy, market-state, and Decision Engine reports as read-only inputs;
- apply incremental round-trip slippage to Freqtrade net historical returns;
- produce chronological train, validation, test, and rolling walk-forward evidence;
- mark fewer than 100 historical trades or 20 forward closed trades as `LOW_SAMPLE`;
- reject shadow promotion when leakage, overfit, sample, net-filter-value, or score gates fail;
- never produce or imply live-trading permission.

## Current Product Meaning

The project remains an evidence collection system, not a stable-profit live system. Real-money trading is forbidden until forward evidence, shadow consistency, net filter value, slippage stress, and Gatekeeper requirements all pass.
