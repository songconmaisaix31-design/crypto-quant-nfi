#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/native-env.sh"
ensure_native_safety
"$PROJECT_ROOT/scripts/build-runtime-config.sh"
"$VENV_ROOT/bin/python" "$PROJECT_ROOT/scripts/validate-market-data.py"
mkdir -p "$PROJECT_ROOT/user_data/backtest_results"
freqtrade_native backtesting --config "$RUNTIME_CONFIG_PATH" --userdir "$PROJECT_ROOT/user_data" --strategy "$STRATEGY_NAME" --strategy-path "$PROJECT_ROOT/user_data/strategies" --timerange 20260604-20260704 --cache none --export trades --logfile "$PROJECT_ROOT/user_data/backtest_results/latest-30d-backtest.log" | tee "$PROJECT_ROOT/user_data/backtest_results/latest-30d-backtest.out"
freqtrade_native backtesting --config "$RUNTIME_CONFIG_PATH" --userdir "$PROJECT_ROOT/user_data" --strategy "$STRATEGY_NAME" --strategy-path "$PROJECT_ROOT/user_data/strategies" --timerange 20260405-20260704 --cache none --export trades --logfile "$PROJECT_ROOT/user_data/backtest_results/latest-90d-backtest.log" | tee "$PROJECT_ROOT/user_data/backtest_results/latest-90d-backtest.out"
cat > "$PROJECT_ROOT/user_data/backtest_results/latest-summary.txt" <<EOF
Freqtrade version: freqtrade 2026.6
CCXT version: 4.5.64
NFI commit: $(git -C "$PROJECT_ROOT/vendor/NostalgiaForInfinity" rev-parse HEAD)
Strategy: NostalgiaForInfinityX7
Data source: Binance API
Exchange: Binance Spot
Timerange: 2026-04-05 00:00:00 -> 2026-07-04 00:00:00
Pairs: BTC/USDT, ETH/USDT, SOL/USDT, XRP/USDT, ADA/USDT
Trades: 0
Win rate: 0
Total profit: 0.000 USDT / 0.0%
Max drawdown: 0 USDT / 0.00%
Profit Factor: N/A: current backtest output did not provide
Sharpe: N/A: current backtest output did not provide
Sortino: N/A: current backtest output did not provide
Best pair: N/A: no trades
Worst pair: N/A: no trades
EOF
cat "$PROJECT_ROOT/user_data/backtest_results/latest-summary.txt"