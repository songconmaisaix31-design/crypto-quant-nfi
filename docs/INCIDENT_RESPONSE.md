# Incident Response

P0 incidents force `BLOCKED` and require manual review before any further live-readiness work.

Incident types include live trading risk, secret leak risk, futures/margin risk, mainnet endpoint risk, exposed FreqUI, uncanceled testnet orders, gatekeeper failure, audit chain failure, and unknown errors.

Create an incident report:

```bash
bash scripts/incident-report.sh --type UNKNOWN_ERROR --detected-by operator
```

