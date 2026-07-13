# Micro-Live Policy

Real small-money live trading is currently `BLOCKED`.

Current prohibitions:

- Real Binance main account API key.
- Real automatic trading.
- Futures.
- Margin.
- Leverage.
- Short.
- Withdrawal permission.
- Public FreqUI.
- API key persisted to disk.
- Key committed to git.
- Key printed in logs.

Minimum future conditions for manual micro-live:

1. Pre-live Gate is not `BLOCKED`.
2. Gatekeeper outputs `MANUAL_MICRO_LIVE_ALLOWED`.
3. Shadow observation >= 14 days, recommended 28 days.
4. Forward closed trades >= 20.
5. Shadow consistency >= 95%.
6. Forward net_filter_value > 0.
7. Slippage stress remains non-negative.
8. Emergency Stop PASS.
9. Testnet order lifecycle PASS.
10. Testnet bot lifecycle PASS.
11. max_open_trades <= 1.
12. daily_max_trades <= 2.
13. max_total_live_capital_usdt is explicitly configured.
14. daily_max_loss_usdt is explicitly configured.
15. API key enables Spot trading only.
16. Withdrawal is disabled.
17. Futures and margin are disabled.
18. IP whitelist is configured.
19. Operator approval file exists.
20. User explicit approval file exists.

Even if all conditions pass, only `MANUAL_MICRO_LIVE_ALLOWED` is possible. `AUTO_MICRO_LIVE_ALLOWED` is policy-blocked.

This is not investment advice. Real trading can lose all capital.

