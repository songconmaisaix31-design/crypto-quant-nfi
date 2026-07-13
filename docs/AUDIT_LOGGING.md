# Audit Logging

Audit events are stored in `user_data/audit/audit_log.jsonl`.

Append an event:

```bash
python3 scripts/audit-log.py --script-name gatekeeper --command "bash scripts/gatekeeper.sh" --phase gatekeeper --status PASS
```

Verify the hash chain:

```bash
bash scripts/audit-verify.sh
```

Secrets are redacted before audit events are written.

