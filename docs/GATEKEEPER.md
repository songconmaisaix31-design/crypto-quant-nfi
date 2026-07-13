# Gatekeeper

Gatekeeper aggregates all live-readiness gates into one authoritative state.

Run:

```bash
bash scripts/gatekeeper.sh
```

Allowed states:

- `BLOCKED`
- `TESTNET_ALLOWED`
- `MANUAL_MICRO_LIVE_ALLOWED`
- `AUTO_MICRO_LIVE_ALLOWED`

Current policy blocks automatic micro-live. Real trading is forbidden unless Gatekeeper explicitly outputs `MANUAL_MICRO_LIVE_ALLOWED`.

