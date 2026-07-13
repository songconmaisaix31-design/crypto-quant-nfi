# Project Memory

## Long-Term Context

- The project is a local Freqtrade dry-run/testnet environment for `NostalgiaForInfinityX7`.
- Main dry-run runtime is intentionally isolated from Binance Spot Testnet checks.
- Pre-live gate v3 remains blocked; testnet practice is allowed, but micro-live/mainnet trading is not allowed.
- Testnet API credentials must be supplied through the active WSL environment as `BINANCE_TESTNET_KEY` and `BINANCE_TESTNET_SECRET`.
- Secret values must not be written to project files, reports, logs, or chat.

## Current Known State

- Main runtime safety requirements: `dry_run=True`, `trading_mode=spot`, `margin_mode=""`, empty exchange credentials, `can_short=False`, FreqUI on `127.0.0.1`.
- Testnet Gate was allowed, but Micro-live Readiness remains blocked due to insufficient forward samples and negative Decision Engine filter value.
- 2026-07-08 Codex-run testnet smoke/order lifecycle checks could not complete because the Codex WSL child process did not inherit the user's manually exported `BINANCE_TESTNET_KEY` and `BINANCE_TESTNET_SECRET`.
- 2026-07-08 user-terminal testnet smoke test passed and Binance Spot Testnet limit-order lifecycle passed: order created, fetched, canceled, and verified canceled on `BTC/USDT`; mainnet was not touched.
- 2026-07-08 Codex updated aggregate testnet reports to reflect smoke/order lifecycle PASS. Testnet bot lifecycle remains blocked from Codex because the current Codex WSL child process does not have testnet credentials.
- Earlier testnet smoke failure was caused by the old endpoint check using `urllib`, which was affected by malformed WSL proxy environment data; ccxt still successfully read markets and account balance.
- Earlier order lifecycle failure was caused by the old test price algorithm using a far-below-market price that violated Binance `PERCENT_PRICE_BY_SIDE`.
- 2026-07-09 forward evidence activation started the main dry-run through the systemd system service. `status-native.sh` reports `RUNNING` with `running_mode=systemd_system_service`, and forward evidence is no longer blocked by a stopped dry-run.
- Micro-live remains blocked after forward evidence activation: forward closed trades are still `0`, shadow observation is about `2` days, and Gatekeeper remains `TESTNET_ALLOWED`.
- 2026-07-13 v1.0 Stable Profit Evidence Loop was added. It creates source registry, compliant/manual community ingestion, hypothesis registry, plan-only optimization experiments, walk-forward and anti-overfit plans, stable profit score, shadow-only promotion pipeline, weekly report, dashboard, hyperopt research plan, and final loop report. It does not modify the original strategy or runtime config and does not allow live trading.
- 2026-07-13 v1.1 converted H1/H5/H7/H8/H3 from plan-only to read-only offline candidate replay over 61 historical Decision Engine rows. `baseline_nfi` remained best historically; `sizing_only_pair_quality_v1` was the best experimental candidate but stayed blocked by negative net filter value, `LOW_SAMPLE`, and `HIGH` overfit risk. No candidate was promoted to shadow or live.
- 2026-07-13 the Evidence Throughput Controller was added at `scripts/evidence_throughput_controller.py`. It separates decision-grade closed forward trades, leading signal/trade events, point-in-time context snapshots, and static historical rows; writes `reports/CONTEXT.md` plus `reports/evidence_throughput/`; and uses the existing 14-day/20-closed-trade minimums for decision ETA. It never controls orders or live promotion.
- 2026-07-13 current controller snapshot is `EVIDENCE_STARVED`: the safe 20-pair evidence-profile dry-run is running, but UTC-today evidence is 0 decision-grade closed trades, 0 leading signal/trade events, and 5 context snapshots. The cumulative gate is 0/20 forward closed trades and 1/14 verified consecutive observation days, so the rolling decision-grade rate is 0/day and ETA is `UNBOUNDED_AT_CURRENT_RATE`.
- 2026-07-13 profitability remains unproven: the 5-pair NFI replay produced no signals, `sizing_only_pair_quality_v1` has negative net filter value, and overfit risk is `HIGH`. Existing sample validation showed that the safe 20-pair research universe produced 21 entries over 180 days and 61 over 365 days. That 20-pair profile is now active for forward dry-run collection without overwriting runtime config or changing NFI; collect closed outcomes before adding factors.
- Shadow journaling now records open-to-closed trade state transitions exactly once. This prevents a trade first observed open from disappearing from the forward closed-trade count when it later closes.
- Tag `v1.0-stable-profit-evidence-loop` points to commit `b70e11b`. During v1.1 acceptance, the native dry-run was running through the systemd system service and forward evidence was no longer blocked by a stopped process.
- 2026-07-13: GitHub publication excludes `.env*`, `user_data/`, generated `reports/`, collected `market_intelligence/` data, and local backups. Local files remain available on disk.
- 2026-07-13: Publishable configuration examples live under `configs/` and contain blank credential fields. The local `user_data/config.sample_validation.json` remains ignored.
- 2026-07-13: A redacted Gitleaks history scan found three legacy generic API key detections in `user_data/config.sample_validation.json`. The existing local history must never be pushed; publish only a sanitized snapshot history.

## Operational Notes

- When debugging testnet checks, inspect generated reports in `reports/testnet_run/` first.
- Do not infer that Codex subprocesses can see user-exported WSL variables unless the command runs in the same environment or the user verifies it.
- For Binance Spot Testnet order lifecycle checks, use a non-crossing limit buy price inside the exchange percent-price filter range and verify minimum notional plus testnet USDT balance before submitting.
- Native dry-run may be carried by a hidden Windows `wsl.exe` process even when the WSL systemd service is inactive; use `scripts/status-native.sh` or `scripts/ensure-dry-run-running.sh` instead of checking only `systemctl`.
- A systemd service started inside a transient `wsl.exe` invocation can receive `SIGINT` and stop when that invocation exits. On Windows, the persistent local launch path is `scripts/start-native-windows.ps1`; verify all three signals with `scripts/status-native.sh`: one Freqtrade trade process, hidden Windows carrier detected, and API health reachable.
- `scripts/start-native-windows.ps1 -Profile evidence -Replace` safely replaces the active collector and launches the safety-checked 20-pair `config.sample_validation.json` for forward dry-run evidence. The default `runtime` profile remains available, `config.runtime.json` is not overwritten, and `scripts/stop-native.sh` handles both profiles.
