# Operations

Use `bash scripts/run-daily-ops.sh` for the normal daily workflow.

Use `bash scripts/run-weekly-ops.sh` for weekly status aggregation.

Use `bash scripts/build-evidence-index.sh` to rebuild the evidence map.

Use `bash scripts/evidence-throughput-controller.sh` to refresh daily evidence
counts, decision ETA, blockers, and `reports/CONTEXT.md`.

On Windows, use `scripts/start-native-windows.ps1` to keep the safe dry-run
alive across transient WSL command sessions. Use `-Profile evidence` for the
validated 20-pair forward-evidence collector without overwriting runtime config;
use `-Replace` when switching from another running profile.

Daily Ops does not require testnet keys and must not enable live trading.
