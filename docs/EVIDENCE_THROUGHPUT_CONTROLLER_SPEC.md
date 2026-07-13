# Evidence Throughput Controller Specification

## Objective

Make the project answer three questions from current, auditable evidence:

1. How much decision-grade evidence was produced today?
2. At the current rate, when can the next shadow-promotion decision be made?
3. What is blocking evidence production or profitability validation now?

The controller measures research progress. It does not modify NFI, trading
configuration, credentials, orders, or live permissions.

## Problem

Existing reports mix operational health, data quality, historical replay, and
forward outcomes. A passing collection job or a high data-confidence score is
not evidence of profitable forward performance. The previous shadow snapshot
also tracked seen trade IDs but not open-to-closed state transitions, so a
trade outcome could be missed after the opening event was recorded.

## Evidence Contract

Evidence is reported as separate units; no synthetic combined score is used.
Daily boundaries use UTC, matching the existing report timestamps and journals.

| class | unit | decision use |
|---|---|---|
| Decision-grade | Closed forward dry-run trade with an outcome | Primary sample for candidate comparison |
| Leading | Baseline NFI signal or newly observed dry-run trade | Measures signal viability, not profitability |
| Context | Point-in-time market-intelligence snapshot | Explains market state; never proves alpha |
| Static | Offline historical replay row | Ranks hypotheses; not daily throughput |

Existing expanded-pair sample validation is reused as static signal-viability
evidence. It may redirect the next action, but it never increases today's or
rolling forward evidence counts and never proves profitability.

Heartbeat rows, repeated candidate rows, report generations, and provider
records do not count as decision-grade evidence.

## Decision Gate

The controller reuses the existing minimum evidence contract from
`configs/optimization_experiment_rules.yaml`:

- at least 14 observation days;
- at least 20 forward closed trades;
- positive candidate net filter value;
- overfit risk below `HIGH`;
- a candidate must improve profit or drawdown versus the baseline before a
  shadow-promotion review.

Meeting the sample targets permits a review; it does not permit live trading.
Gatekeeper remains authoritative.

## Status Rules

- `EVIDENCE_BLOCKED`: the safe dry-run is stopped or unsafe.
- `EVIDENCE_STARVED`: the dry-run is running, the forward sample is below the
  target, and the rolling decision-grade rate is zero.
- `COLLECTING`: evidence is increasing but sample gates are not yet met.
- `QUALITY_BLOCKED`: sample gates are met but profitability or overfit gates
  fail; waiting alone will not solve it.
- `READY_FOR_SHADOW_REVIEW`: sample and quality gates pass. This still cannot
  enable live trading.

If the closed-trade rate is zero, ETA is `UNBOUNDED_AT_CURRENT_RATE`. Otherwise
ETA is the slower of the remaining observation-days requirement and the
remaining forward-closed-trades requirement at the rolling seven-day rate.

## Outputs

### `reports/evidence_throughput/evidence_throughput_summary.json`

Required top-level fields:

- `generated_at`
- `status`
- `collection_status`
- `decision_status`
- `today`
- `rolling_7d`
- `cumulative`
- `targets`
- `eta`
- `quality`
- `research_signal_viability`
- `blockers`
- `profitability_direction`
- `safety`

### `reports/evidence_throughput/evidence_throughput_history.csv`

Append-only controller snapshots. Repeated runs are operational snapshots and
must never be counted as new evidence.

### `reports/evidence_throughput/evidence_throughput_report.md`

Human-readable throughput report using the same summary contract.

### `reports/CONTEXT.md`

The current decision packet. It includes live runtime state, freshness,
evidence produced today, rolling rates, ETA, candidate quality, blockers,
safety boundaries, and the single next action.

On Windows, persistent WSL collection uses
`scripts/start-native-windows.ps1`. A systemd service started inside a
transient `wsl.exe` invocation can stop when that invocation exits.
The `evidence` launch profile reuses the safety-checked 20-pair sample config
for forward dry-run collection while leaving `config.runtime.json` untouched.

## Integration

- `scripts/run-daily-ops.sh` always attempts the controller as a finalizer,
  including after an earlier safety-critical failure.
- The evidence index lists the controller outputs.
- Shadow journaling records an explicit close transition and exposes
  `forward_closed_trades`.

## Acceptance Criteria

- A stopped dry-run produces `EVIDENCE_BLOCKED`, zero decision-grade throughput,
  and an unbounded ETA.
- A running dry-run with zero closed outcomes produces `EVIDENCE_STARVED`.
- A positive rate produces a finite, ceiling-rounded ETA.
- Candidate rows and heartbeats cannot inflate evidence counts.
- Existing expanded-pair validation is reused without being counted as forward
  evidence or rerun unnecessarily.
- Open-to-closed trade transitions are recorded exactly once.
- `reports/CONTEXT.md` is generated without reading or exposing `.env` or
  credential values.
- Existing dry-run, spot-only, no-short, localhost-only, and no-live boundaries
  remain unchanged.
- The evidence profile is reported as active only when the running process uses
  at least the validated research pair count.

## Verification

- Run focused unit tests for evidence de-duplication, status, and ETA.
- Run the project test suite.
- Run Python compilation checks for changed modules.
- Run the controller against the current workspace and confirm its outputs
  match the live runtime state.
- Run secret scan and verify no live-order capability was introduced.
