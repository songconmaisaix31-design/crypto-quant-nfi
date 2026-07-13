# Ops Hardening, Audit, and Gatekeeper Goal

## Current State

- Main runtime remains `dry_run=True`, `trading_mode=spot`, `margin_mode=""`, `can_short=False`.
- Main runtime exchange credentials must remain empty.
- FreqUI must remain bound to `127.0.0.1`.
- Testnet evidence can be used for practice, but real mainnet trading is forbidden.
- Pre-live Gate v3 and Micro-live Readiness are expected to remain `BLOCKED`.

## Objective

Build an auditable operations layer around the existing Freqtrade + NFI X7 project:

- Unified Gatekeeper authority.
- Append-only audit ledger with hash-chain verification.
- Secret scanning and redaction checks.
- Manual testnet secret injection loop.
- Workflow state machine.
- Daily and weekly operations reports.
- Sanitized config snapshots and data manifests.
- Evidence index and project status map.
- Incident response runbooks.
- Tests and final hardening report.

## Forbidden Actions

- Do not enable real trading.
- Do not write API keys, secrets, passwords, tokens, or private keys to disk.
- Do not modify `.env`.
- Do not modify `user_data/config.runtime.json`.
- Do not modify original strategy files.
- Do not enable futures, margin, leverage, or shorting.
- Do not bypass pre-live or micro-live gates.
- Do not turn `TESTNET_KEY_MISSING` into a false pass.

## Module Breakdown

1. Gatekeeper.
2. Audit ledger and secret scan.
3. Manual testnet secret loop.
4. Workflow state.
5. Daily and weekly ops.
6. Config snapshot and data manifest.
7. Evidence index.
8. Incident response.
9. Tests.
10. Documentation and final report.

## Acceptance Criteria

- Gatekeeper never emits `MANUAL_MICRO_LIVE_ALLOWED` unless all required evidence exists.
- `AUTO_MICRO_LIVE_ALLOWED` is policy-blocked.
- Audit log hash chain can be verified.
- Secret scan redacts suspected secrets and does not print full secret values.
- Daily Ops can run without testnet keys.
- Manual testnet script reads keys with `read -s`, exports only to child processes, and unsets them on exit.
- Evidence index and project status are generated.
- Emergency stop remains `PASS`.
- Main runtime safety remains unchanged.

## Failure Degradation

- Safety failure: force `BLOCKED`.
- Audit verification failure: force `BLOCKED`.
- Missing testnet key: report `TESTNET_KEY_MISSING`, do not treat as safety failure.
- Non-safety ops failure: continue report generation and mark the module degraded.
- P0 incident: force `INCIDENT_BLOCKED`.

## Expected Final State

- Gatekeeper status is `TESTNET_ALLOWED` or `BLOCKED`.
- Pre-live remains `BLOCKED`.
- Micro-live remains `BLOCKED`.
- Allowed actions are limited to dry-run, shadow observation, and testnet practice.
- This project does not provide investment advice and does not prove future profitability.

