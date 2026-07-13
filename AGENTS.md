# Project Agent Instructions

## Project

- Name: crypto-quant-nfi
- Date created: 2026-07-08
- Runtime: WSL + Python + Freqtrade + Binance Spot Testnet/Dry-run
- Main directories: `scripts/`, `configs/`, `user_data/`, `reports/`, `vendor/`

## Safety Rules

- Do not modify `.env`.
- Do not overwrite `user_data/config.runtime.json`.
- Do not modify the original strategy file.
- Do not print, store, or commit API keys, secrets, passwords, tokens, or private keys.
- Main runtime must remain `dry_run=True`.
- Main runtime must remain spot-only: `trading_mode=spot`, `margin_mode=""`, `can_short=False`.
- Do not enable futures, margin, leverage, shorting, or real mainnet trading.
- FreqUI must remain bound to `127.0.0.1`.
- Testnet credentials may only come from environment variables.

## Commands

- Testnet config: `bash scripts/build-testnet-config.sh`
- Testnet smoke test: `bash scripts/testnet-smoke-test.sh`
- Testnet order lifecycle: `bash scripts/testnet-order-lifecycle-check.sh`
- Testnet status: `bash scripts/status-testnet.sh`
- Emergency stop check: `bash scripts/emergency-stop-check.sh`

## Editing Policy

- Keep changes narrowly scoped to the requested diagnostic, gate, or testnet workflow.
- Do not delete historical data, databases, logs, reports, Docker resources, or user files unless explicitly requested.
- Reports may be regenerated under `reports/`.
- Local testnet config may be regenerated at `user_data/config.testnet.local.json`, but must stay ignored by git and must not contain credential values.

