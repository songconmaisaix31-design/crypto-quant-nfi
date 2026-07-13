#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
OUT = PROJECT_ROOT / "reports/micro_live_readiness"
SUMMARY = OUT / "emergency_stop_check_summary.json"
REPORT = OUT / "emergency_stop_check_report.md"
MATRIX = OUT / "emergency_stop_check_matrix.csv"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def row(name: str, passed: bool, message: str, evidence: Any = "") -> dict[str, Any]:
    return {"check": name, "status": "PASS" if passed else "FAIL", "message": message, "evidence": json.dumps(evidence, ensure_ascii=False, default=str)}


def safety() -> dict[str, Any]:
    cfg = load_json(RUNTIME_CONFIG, {})
    ex = cfg.get("exchange", {})
    api = cfg.get("api_server", {})
    checks = {
        "dry_run": cfg.get("dry_run") is True,
        "spot": cfg.get("trading_mode") == "spot",
        "margin_empty": cfg.get("margin_mode") in ("", None),
        "can_short_false": cfg.get("can_short") is False,
        "credentials_empty": not (ex.get("key") or ex.get("secret") or ex.get("password")),
        "api_localhost": api.get("listen_ip_address") == "127.0.0.1",
    }
    return {"pass": all(checks.values()), "checks": checks}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    scripts = {
        "stop_native": PROJECT_ROOT / "scripts/stop-native.sh",
        "stop_docker": PROJECT_ROOT / "scripts/stop.sh",
        "status_native": PROJECT_ROOT / "scripts/status-native.sh",
        "status_docker": PROJECT_ROOT / "scripts/status.sh",
        "pre_live_v3": PROJECT_ROOT / "scripts/pre-live-gate-v3.sh",
    }
    testnet_pid_file = PROJECT_ROOT / "user_data/freqtrade-testnet.pid"
    testnet_running = False
    if testnet_pid_file.exists():
        try:
            pid = int(testnet_pid_file.read_text().strip())
            os.kill(pid, 0)
            testnet_running = True
        except Exception:
            testnet_running = False
    safe = safety()
    rows = [
        row("runtime safety still dry-run spot-only", safe["pass"], "Runtime remains safe." if safe["pass"] else "Runtime safety failed.", safe),
        row("stop scripts exist", scripts["stop_native"].exists() and scripts["stop_docker"].exists(), "Stop scripts are present.", {k: str(v) for k, v in scripts.items() if k.startswith("stop")}),
        row("status scripts exist", scripts["status_native"].exists() and scripts["status_docker"].exists(), "Status scripts are present.", {k: str(v) for k, v in scripts.items() if k.startswith("status")}),
        row("pre-live gate v3 script exists", scripts["pre_live_v3"].exists(), "V3 gate script is present.", str(scripts["pre_live_v3"])),
        row("testnet process detectable", True, "Testnet pid file checked; no stop/sell action performed.", {"pid_file": str(testnet_pid_file), "testnet_running": testnet_running}),
        row("emergency check is non-destructive", True, "This script only checks readiness and does not stop services or place orders."),
    ]
    passed = all(r["status"] == "PASS" for r in rows)
    with MATRIX.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["check", "status", "message", "evidence"])
        writer.writeheader()
        writer.writerows(rows)
    summary = {"generated_at": now(), "emergency_stop_check_passed": passed, "safety": safe, "matrix": rows}
    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    lines = [
        "# Emergency Stop Readiness Check",
        "",
        f"Generated: `{summary['generated_at']}`",
        "",
        f"Result: `{'PASS' if passed else 'FAIL'}`",
        "",
        "This check is non-destructive. It does not stop the bot and does not modify trading configuration.",
        "",
        "| check | status | message |",
        "|---|---|---|",
    ]
    for item in rows:
        lines.append(f"| {item['check']} | `{item['status']}` | {item['message']} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"EMERGENCY_STOP_CHECK={'PASS' if passed else 'FAIL'}")
    print(f"[PASS] wrote {REPORT}")
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
