#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
OUT = PROJECT_ROOT / "reports/testnet_gate"
REPORT = OUT / "testnet_gate_report.md"
SUMMARY = OUT / "testnet_gate_summary.json"
MATRIX = OUT / "testnet_gate_matrix.csv"
LOGS = OUT / "testnet_gate_logs.txt"
SHADOW_SIGNAL = PROJECT_ROOT / "user_data/shadow_decision/latest_signal_snapshot.json"
SHADOW_SUMMARY = PROJECT_ROOT / "reports/shadow_decision/shadow_decision_summary.json"
PRELIVE_V3 = PROJECT_ROOT / "reports/pre_live_gate/pre_live_gate_v3_summary.json"
TESTNET_TEMPLATE = PROJECT_ROOT / "configs/config.testnet.template.json"

STATUSES = ("BLOCKED", "TESTNET_ALLOWED", "MANUAL_MICRO_LIVE_ALLOWED", "AUTO_MICRO_LIVE_ALLOWED")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def safety() -> dict[str, Any]:
    cfg = load_json(RUNTIME_CONFIG, {})
    ex = cfg.get("exchange", {})
    api = cfg.get("api_server", {})
    checks = {
        "dry_run": cfg.get("dry_run") is True,
        "trading_mode_spot": cfg.get("trading_mode") == "spot",
        "margin_mode_empty": cfg.get("margin_mode") in ("", None),
        "can_short_false": cfg.get("can_short") is False,
        "credentials_empty": not (ex.get("key") or ex.get("secret") or ex.get("password")),
        "api_localhost": api.get("listen_ip_address") == "127.0.0.1",
    }
    return {"pass": all(checks.values()), "checks": checks}


def row(gate: str, passed: bool, message: str, evidence: Any = "") -> dict[str, Any]:
    return {"gate": gate, "status": "PASS" if passed else "FAIL", "message": message, "evidence": json.dumps(evidence, ensure_ascii=False, default=str)}


def template_safe(path: Path) -> dict[str, Any]:
    cfg = load_json(path, {})
    ex = cfg.get("exchange", {})
    checks = {
        "exists": path.exists(),
        "dry_run_true": cfg.get("dry_run") is True,
        "spot": cfg.get("trading_mode") == "spot",
        "margin_empty": cfg.get("margin_mode") in ("", None),
        "can_short_false": cfg.get("can_short") is False,
        "credentials_empty": not (ex.get("key") or ex.get("secret") or ex.get("password")),
    }
    return {"pass": all(checks.values()), "checks": checks}


def run_emergency_check(log: list[str]) -> dict[str, Any]:
    cmd = ["bash", "scripts/emergency-stop-check.sh"]
    try:
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=60)
        log.append("$ " + " ".join(cmd))
        log.append(proc.stdout)
        if proc.stderr:
            log.append(proc.stderr)
        return {"pass": proc.returncode == 0, "returncode": proc.returncode}
    except Exception as exc:
        return {"pass": False, "error": repr(exc)}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    log: list[str] = [f"generated_at={now()}", f"project={PROJECT_ROOT}"]
    before = RUNTIME_CONFIG.read_bytes() if RUNTIME_CONFIG.exists() else b""
    safe = safety()
    signal = load_json(SHADOW_SIGNAL, {})
    shadow = load_json(SHADOW_SUMMARY, {})
    prelive = load_json(PRELIVE_V3, {})
    tmpl = template_safe(TESTNET_TEMPLATE)
    emergency = run_emergency_check(log)
    signal_status = signal.get("signal_detection_status") or shadow.get("signal_detection_status")
    detection_ok = signal_status in ("confirmed_signal", "confirmed_no_signal", "inferred_from_trade")
    rows = [
        row("runtime remains safe", safe["pass"], "Runtime is dry-run spot-only with no credentials." if safe["pass"] else "Runtime safety failed.", safe),
        row("testnet template is safe by default", tmpl["pass"], "Template exists and contains no credentials/live settings." if tmpl["pass"] else "Template is missing or unsafe.", tmpl),
        row("signal detection is explicit", detection_ok, f"signal_detection_status={signal_status}", {"signal_detection_status": signal_status}),
        row("FreqUI/dry-run bot status readable", bool(shadow.get("api_available") or shadow.get("bot_running")), "Bot/API status evidence is readable.", {"api_available": shadow.get("api_available"), "bot_running": shadow.get("bot_running")}),
        row("emergency stop readiness check passed", emergency.get("pass") is True, "Emergency stop readiness is present.", emergency),
        row("pre-live gate may remain blocked for testnet", True, "Testnet observation can be allowed while live trading remains blocked.", {"pre_live_blocked": prelive.get("live_trading_blocked")}),
    ]
    runtime_untouched = before == (RUNTIME_CONFIG.read_bytes() if RUNTIME_CONFIG.exists() else b"")
    if not runtime_untouched:
        rows.append(row("runtime config unchanged", False, "Runtime config changed during testnet gate."))
    status = "TESTNET_ALLOWED" if all(r["status"] == "PASS" for r in rows) else "BLOCKED"
    with MATRIX.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["gate", "status", "message", "evidence"])
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "generated_at": now(),
        "status": status,
        "allowed_statuses": STATUSES,
        "testnet_allowed": status == "TESTNET_ALLOWED",
        "micro_live_allowed": False,
        "runtime_config_untouched": runtime_untouched,
        "safety": safe,
        "signal_detection_status": signal_status,
        "pre_live_gate_status": "BLOCKED" if prelive.get("live_trading_blocked", True) else "PASS",
        "matrix": rows,
        "blockers": [r["gate"] for r in rows if r["status"] != "PASS"],
    }
    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    lines = [
        "# Testnet Gate",
        "",
        f"Generated: `{summary['generated_at']}`",
        "",
        f"Status: `{status}`",
        "",
        "This gate permits at most testnet or continued dry-run observation. It does not enable real trading or add API keys.",
        "",
        "| gate | status | message |",
        "|---|---|---|",
    ]
    for item in rows:
        lines.append(f"| {item['gate']} | `{item['status']}` | {item['message']} |")
    lines += [
        "",
        "## Decision",
        f"- Testnet allowed: `{status == 'TESTNET_ALLOWED'}`",
        "- Micro-live allowed: `False`",
        "- Real trading remains blocked by separate pre-live/micro-live gates.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGS.write_text("\n".join(log) + "\n", encoding="utf-8")
    print(f"TESTNET_GATE_STATUS={status}")
    print(f"[PASS] wrote {REPORT}")
    return 0 if status == "TESTNET_ALLOWED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
