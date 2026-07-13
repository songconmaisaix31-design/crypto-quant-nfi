# Runbook

Daily operations:

```bash
bash scripts/run-daily-ops.sh
```

Persistent Windows dry-run collection:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-native-windows.ps1
```

Validated 20-pair forward-evidence profile:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-native-windows.ps1 -Profile evidence -Replace
```

This profile reads `user_data/config.sample_validation.json`; it does not
overwrite `user_data/config.runtime.json`. `-Replace` performs the controlled
stop before changing profiles so two collectors cannot compete for the API port.

Current evidence throughput and decision ETA:

```bash
bash scripts/evidence-throughput-controller.sh
```

Read `reports/CONTEXT.md` for the current decision packet. A transient WSL
systemd start is not the persistent Windows launch path.

Gatekeeper:

```bash
bash scripts/gatekeeper.sh
```

Emergency stop readiness:

```bash
bash scripts/emergency-stop-check.sh
```

Manual testnet key run:

```bash
bash scripts/run-testnet-manual-secret.sh
```

Do not store keys in `.env`, config files, reports, logs, or git.
