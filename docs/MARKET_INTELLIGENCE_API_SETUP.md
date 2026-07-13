# Market Intelligence API Setup

Public collection uses Binance Spot Market Data Only, Alternative.me, and Coin
Metrics Community without credentials.

Optional provider credentials are read from the active process environment:

```text
COINGECKO_API_KEY
CRYPTOPANIC_API_TOKEN
FRED_API_KEY
REDDIT_CLIENT_ID
REDDIT_CLIENT_SECRET
LUNARCRUSH_API_KEY
SANTIMENT_API_KEY
GLASSNODE_API_KEY
COINGLASS_API_KEY
```

Do not place these values in `.env`, project config, reports, shell history, or
Git. Verify only status with:

```bash
bash scripts/check-market-intelligence-credentials.sh
```

Providers requiring terms review remain `TERMS_BLOCKED` after credentials are
present until their intended use has been reviewed. Missing credentials produce
`KEY_MISSING` and do not fail the public-source pipeline.
