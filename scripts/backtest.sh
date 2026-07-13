#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

ensure_dry_run_config
strategy="$(strategy_name)"
timerange="${TIMERANGE:-$(date -u -d '90 days ago' +%Y%m%d)-}"
result_dir="$PROJECT_ROOT/user_data/backtest_results"
mkdir -p "$result_dir"

echo "Backtesting ${strategy}, timerange ${timerange}"
compose run --rm freqtrade backtesting \
  --config /freqtrade/user_data/config.json \
  --strategy "$strategy" \
  --strategy-path /freqtrade/user_data/strategies/nfi \
  --timerange "$timerange" \
  --fee 0.001 \
  --export trades \
  --export-filename /freqtrade/user_data/backtest_results/latest-backtest.json \
  | tee "$result_dir/latest-backtest.log"

python3 - "$result_dir/latest-summary.txt" "$strategy" "$timerange" "$result_dir/latest-backtest.log" <<'PY'
import re, sys, pathlib
out, strategy, timerange, log_path = sys.argv[1:]
text = pathlib.Path(log_path).read_text(encoding="utf-8", errors="ignore")
def find(pattern, default="N/A"):
    m = re.search(pattern, text, re.I)
    return m.group(1).strip() if m else default
summary = [
    f"Backtest timerange: {timerange}",
    f"Strategy: {strategy}",
    f"Trades: {find(r'TOTAL\\s+\\S*\\s*(\\d+)')}",
    f"Winning trades: {find(r'Win\\s+Draw\\s+Loss\\s+Win%.*?\\n.*?\\s(\\d+)\\s+\\d+\\s+\\d+\\s+[\\d.]+', 'See latest-backtest.log')}",
    f"Losing trades: {find(r'Win\\s+Draw\\s+Loss\\s+Win%.*?\\n.*?\\s\\d+\\s+\\d+\\s+(\\d+)\\s+[\\d.]+', 'See latest-backtest.log')}",
    f"Win rate: {find(r'Win%\\s*\\|?\\s*([\\d.]+)', 'See latest-backtest.log')}",
    f"Total profit: {find(r'Total profit %\\s*│\\s*([^│]+)', find(r'Total profit %\\s+([^\\n]+)'))}",
    f"Max drawdown: {find(r'Absolute Drawdown .*?\\s(\\S+\\s*%)', find(r'Max % of account underwater\\s*│\\s*([^│]+)'))}",
    f"Average duration: {find(r'Avg Duration\\s*│\\s*([^│]+)', find(r'Avg Duration\\s+([^\\n]+)'))}",
    f"Best pair: {find(r'Best Pair\\s*│\\s*([^│]+)', find(r'Best Pair\\s+([^\\n]+)'))}",
    f"Worst pair: {find(r'Worst Pair\\s*│\\s*([^│]+)', find(r'Worst Pair\\s+([^\\n]+)'))}",
    f"Profit Factor: {find(r'Profit factor\\s*│\\s*([^│]+)', find(r'Profit factor\\s+([^\\n]+)'))}",
    f"Sharpe Ratio: {find(r'Sharpe\\s*│\\s*([^│]+)', find(r'Sharpe\\s+([^\\n]+)'))}",
    f"Sortino Ratio: {find(r'Sortino\\s*│\\s*([^│]+)', find(r'Sortino\\s+([^\\n]+)'))}",
]
pathlib.Path(out).write_text("\n".join(summary) + "\n", encoding="utf-8")
print("\n".join(summary))
PY
echo "[PASS] Summary: $result_dir/latest-summary.txt"

