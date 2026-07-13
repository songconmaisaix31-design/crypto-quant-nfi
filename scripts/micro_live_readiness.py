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
OUT = PROJECT_ROOT / "reports/micro_live_readiness"
REPORT = OUT / "micro_live_readiness_report.md"
SUMMARY = OUT / "micro_live_readiness_summary.json"
MATRIX = OUT / "micro_live_readiness_matrix.csv"
LOGS = OUT / "micro_live_readiness_logs.txt"
PRELIVE_V3 = PROJECT_ROOT / "reports/pre_live_gate/pre_live_gate_v3_summary.json"
SHADOW_SIGNAL = PROJECT_ROOT / "user_data/shadow_decision/latest_signal_snapshot.json"
SHADOW_DECISION = PROJECT_ROOT / "reports/shadow_decision/shadow_decision_summary.json"
V2_SUMMARY = PROJECT_ROOT / "reports/decision_engine_v2/decision_engine_v2_summary.json"
MICRO_TEMPLATE = PROJECT_ROOT / "configs/config.micro_live.template.json"
RULES = PROJECT_ROOT / "configs/micro_live_rules.yaml"

STATUSES = ("BLOCKED", "TESTNET_ALLOWED", "MANUAL_MICRO_LIVE_ALLOWED", "AUTO_MICRO_LIVE_ALLOWED")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def as_float(v: Any, default: float = 0.0) -> float:
    try:
        if v in ("", None):
            return default
        return float(v)
    except Exception:
        return default


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
        "max_open_trades_limited": int(cfg.get("max_open_trades") or 999) <= 1,
    }
    return {"pass": all(checks.values()), "checks": checks}


def emergency(log: list[str]) -> dict[str, Any]:
    try:
        proc = subprocess.run(["bash", "scripts/emergency-stop-check.sh"], cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=60)
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
    prelive = load_json(PRELIVE_V3, {})
    signal = load_json(SHADOW_SIGNAL, {})
    shadow = load_json(SHADOW_DECISION, {})
    v2 = load_json(V2_SUMMARY, {})
    tmpl = template_safe(MICRO_TEMPLATE)
    emer = emergency(log)
    prelive_pass = prelive.get("live_trading_approved") is True
    signal_status = signal.get("signal_detection_status") or shadow.get("signal_detection_status")
    observation_days = int(shadow.get("observation_days") or 0)
    observed_events = int(shadow.get("observed_events") or 0)
    forward_closed = int(shadow.get("forward_closed_trades") or 0)
    consistency = shadow.get("consistency_rate")
    consistency_ok = consistency is not None and as_float(consistency) >= 0.95
    v2_net = as_float(v2.get("v2_net_filter_value"), as_float((v2.get("v2_all") or {}).get("net_filter_value")))
    rows = [
        row("runtime remains safe", safe["pass"], "Runtime is dry-run spot-only with no credentials." if safe["pass"] else "Runtime safety failed.", safe),
        row("micro-live template is blocked/safe by default", tmpl["pass"], "Template is capped, dry-run, and credential-free." if tmpl["pass"] else "Template missing or unsafe.", tmpl),
        row("micro live rules exist", RULES.exists(), "Rules file exists.", str(RULES)),
        row("pre-live gate v3 passed", prelive_pass, "Pre-live gate v3 passed." if prelive_pass else "Pre-live gate v3 is still BLOCKED.", {"live_trading_approved": prelive.get("live_trading_approved")}),
        row("shadow observation >= 14 days", observation_days >= 14, f"observation_days={observation_days}.", {"observation_days": observation_days}),
        row("forward observed events/trades >= 20", max(forward_closed, observed_events) >= 20, f"forward_closed={forward_closed}, observed_events={observed_events}.", {"forward_closed_trades": forward_closed, "observed_events": observed_events}),
        row("signal detection explicit", signal_status in ("confirmed_signal", "confirmed_no_signal", "inferred_from_trade"), f"signal_detection_status={signal_status}.", {"signal_detection_status": signal_status}),
        row("dry-run consistency >= 95%", consistency_ok, f"consistency_rate={consistency}.", {"consistency_rate": consistency}),
        row("decision engine v2 net_filter_value positive", v2_net > 0, f"v2_net_filter_value={v2_net}.", {"v2_net_filter_value": v2_net}),
        row("emergency stop readiness passed", emer.get("pass") is True, "Emergency stop readiness check passed." if emer.get("pass") else "Emergency stop readiness failed.", emer),
        row("manual approval present", False, "Manual approval is intentionally absent; real micro-live remains blocked.", {}),
    ]
    runtime_untouched = before == (RUNTIME_CONFIG.read_bytes() if RUNTIME_CONFIG.exists() else b"")
    if not runtime_untouched:
        rows.append(row("runtime config unchanged", False, "Runtime config changed during readiness check."))
    hard_pass = all(r["status"] == "PASS" for r in rows)
    status = "AUTO_MICRO_LIVE_ALLOWED" if hard_pass else "BLOCKED"
    blockers = [r["gate"] for r in rows if r["status"] != "PASS"]
    with MATRIX.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["gate", "status", "message", "evidence"])
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "generated_at": now(),
        "status": status,
        "allowed_statuses": STATUSES,
        "testnet_allowed_possible": True,
        "manual_micro_live_allowed": False,
        "auto_micro_live_allowed": False,
        "runtime_config_untouched": runtime_untouched,
        "signal_detection_status": signal_status,
        "pre_live_gate_status": "PASS" if prelive_pass else "BLOCKED",
        "v2_net_filter_value": v2_net,
        "observation_days": observation_days,
        "forward_closed_trades": forward_closed,
        "observed_events": observed_events,
        "matrix": rows,
        "blockers": blockers,
    }
    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    lines = [
        "# Micro-Live Readiness",
        "",
        f"Generated: `{summary['generated_at']}`",
        "",
        f"Status: `{status}`",
        "",
        "Real micro-live remains forbidden unless every hard gate passes. This script does not enable live trading or add API keys.",
        "",
        "| gate | status | message |",
        "|---|---|---|",
    ]
    for item in rows:
        lines.append(f"| {item['gate']} | `{item['status']}` | {item['message']} |")
    lines += [
        "",
        "## Blockers",
    ]
    lines += [f"- {b}" for b in blockers] or ["- None"]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGS.write_text("\n".join(log) + "\n", encoding="utf-8")
    print(f"MICRO_LIVE_READINESS_STATUS={status}")
    print(f"[PASS] wrote {REPORT}")
    if status == "BLOCKED":
        print("[BLOCKED] micro-live is not allowed")
    return 0 if status != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
