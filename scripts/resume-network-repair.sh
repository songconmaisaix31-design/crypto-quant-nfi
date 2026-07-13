#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"
cd "$PROJECT_ROOT"
mkdir -p user_data/logs/network-repair
ts=$(date +%Y%m%d-%H%M%S)
log="user_data/logs/network-repair/resume-network-repair-${ts}.log"
{
  echo "== date =="; date
  echo "== uname =="; uname -a
  echo "== resolv =="; cat /etc/resolv.conf || true
  echo "== route =="; ip route show default || true
  host=$(ip route show default | awk '{print $3; exit}')
  echo "windows_host=$host"
  for proxy in "http://127.0.0.1:7890" "http://${host}:7890"; do
    echo "== $proxy exchangeInfo =="
    if curl --proxy "$proxy" --connect-timeout 15 --max-time 30 -fsS "https://api.binance.com/api/v3/exchangeInfo" -o /tmp/binance-exchange-info.json; then
      python3 -c "import json; print('symbols', len(json.load(open('/tmp/binance-exchange-info.json'))['symbols']))"
    else
      echo "FAIL exchangeInfo via $proxy"
    fi
    echo "== $proxy time =="
    curl --proxy "$proxy" --connect-timeout 15 --max-time 30 -fsS "https://api.binance.com/api/v3/time" || echo "FAIL time via $proxy"
  done
} 2>&1 | tee "$log"
echo "resume_log=$log"