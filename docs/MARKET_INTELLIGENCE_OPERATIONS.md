# Market Intelligence Operations

## Daily

```bash
bash scripts/check-market-intelligence-credentials.sh
bash scripts/collect-market-intelligence.sh
bash scripts/build-market-intelligence-features.sh
bash scripts/market-intelligence-shadow-journal.sh
bash scripts/market-intelligence-daily-report.sh
```

`run-daily-ops.sh` runs this chain automatically. A provider outage is isolated
and lowers data confidence. Inspect `reports/market_intelligence/source_health_report.md`
and `market_intelligence_logs.txt` before troubleshooting.

## Weekly

```bash
bash scripts/evaluate-market-intelligence.sh
bash scripts/market-intelligence-ablation.sh
bash scripts/market-intelligence-walkforward.sh
bash scripts/market-intelligence-weekly-report.sh
```

Do not interpret IC, ablation, or candidate metrics until sufficient local
point-in-time history exists. Current historical provider data must not be
retroactively treated as contemporaneously available.
