# Freqtrade + NostalgiaForInfinity Native Dry-run

This project is for backtesting and dry-run only. It must not be used for live trading without separate review, long dry-run validation, and explicit configuration changes outside this setup.

## Default Mode

WSL native mode is the default path. Docker targets remain available as a fallback, but normal commands use the Python virtualenv under:

```text
$HOME/.local/share/crypto-quant-nfi/freqtrade/.venv
```

## Common Commands

```bash
cd /mnt/d/AI-Workspace/Projects/crypto-quant-nfi
make setup
make validate
make download-data
make backtest
make install-ui
make start
make status
make logs
make stop
```

Docker fallback commands:

```bash
make docker-pull
make docker-validate
make docker-start
make docker-stop
```

## Safety

The generated native config is `user_data/config.native.json`.

Required safety settings:

- `dry_run=true`
- `trading_mode=spot`
- `margin_mode=""`
- `can_short=false`
- empty exchange key, secret, and password
- Web UI bound to `127.0.0.1:8080`

The native scripts validate these settings before setup, download, backtest, and start. `.env` is loaded only for local Web UI credentials; native scripts ignore `.env` overrides for exchange name and strategy so the generated config remains authoritative.

## Strategy

The strategy is symlinked from:

```text
vendor/NostalgiaForInfinity/NostalgiaForInfinityX7.py
```

to:

```text
user_data/strategies/NostalgiaForInfinityX7.py
```

The generated timeframes are read from the strategy and stored in `user_data/runtime-timeframes.txt`.

## Runtime

When WSL user systemd is available, `make setup` writes:

```text
~/.config/systemd/user/crypto-quant-nfi.service
```

`make start`, `make stop`, and `make status` use that service. If systemd is unavailable, scripts fall back to a PID-file based foreground wrapper.

## Current Network Note

Docker Hub large image pulls previously failed with `short read / unexpected EOF`. Native Freqtrade is installed and strategy loading works, but exchange public API access from WSL has been unstable. `make validate` leaves the latest CCXT market-load error at:

```text
user_data/logs/list-markets-binance.err
```

Do not fake data or backtest results when exchange data download fails.
# Ops Hardening Status

This project is currently a dry-run, shadow-observation, and Binance Spot Testnet practice environment. It is not an automatic real-money trading system.

Allowed now:

- Freqtrade dry-run.
- Shadow decision observation.
- Binance Spot Testnet checks.

Forbidden now:

- Real Binance main-account API keys.
- Real small-money live trading.
- Futures, margin, leverage, or shorting.
- Public FreqUI.
- API keys in `.env`, config files, reports, logs, or git.

Core operations:

```bash
bash scripts/gatekeeper.sh
bash scripts/run-daily-ops.sh
bash scripts/build-evidence-index.sh
bash scripts/emergency-stop-check.sh
```

Manual Binance Spot Testnet key run:

```bash
bash scripts/run-testnet-manual-secret.sh
```

Micro-live remains `BLOCKED` unless Gatekeeper explicitly outputs `MANUAL_MICRO_LIVE_ALLOWED`. `AUTO_MICRO_LIVE_ALLOWED` is policy-blocked. This is not investment advice; real trading can lose all capital.
# Multi-Source Market Intelligence

The project includes a read-only, point-in-time market intelligence sidecar.
It collects public spot, global sentiment, and core onchain snapshots; optional
keyed providers degrade to status-only when credentials are missing. External
data affects shadow research and sizing proposals only. It never modifies NFI,
submits orders, or grants live permission.

Run the daily sidecar through `bash scripts/run-daily-ops.sh` or the focused
commands documented in `docs/MARKET_INTELLIGENCE_OPERATIONS.md`.

## Evidence Throughput

`bash scripts/evidence-throughput-controller.sh` generates `reports/CONTEXT.md`
and reports decision-grade evidence produced today, rolling throughput, and the
estimated time to the next shadow-promotion decision. A stopped collector or a
zero forward-outcome rate is reported explicitly; data confidence is never
treated as profitability confidence.
