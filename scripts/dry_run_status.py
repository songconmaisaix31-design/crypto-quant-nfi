#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
EVIDENCE_CONFIG = PROJECT_ROOT / "user_data/config.sample_validation.json"
ALLOWED_DRY_RUN_CONFIGS = (RUNTIME_CONFIG, EVIDENCE_CONFIG)
PID_FILE = PROJECT_ROOT / "user_data/freqtrade-native.pid"
LOG_FILE = PROJECT_ROOT / "user_data/logs/freqtrade-native.log"
SYSTEM_SERVICE = "crypto-quant-nfi.service"


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=PROJECT_ROOT, text=True, capture_output=True)


def load_runtime_safety(config_path: Path = RUNTIME_CONFIG) -> dict[str, Any]:
    cfg = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    ex = cfg.get("exchange", {})
    api = cfg.get("api_server", {})
    checks = {
        "dry_run": cfg.get("dry_run") is True,
        "trading_mode_spot": cfg.get("trading_mode") == "spot",
        "margin_mode_empty": cfg.get("margin_mode") in ("", None),
        "can_short_false": cfg.get("can_short") is False,
        "exchange_credentials_empty": not any(ex.get(k) for k in ("key", "secret", "password")),
        "api_localhost": api.get("listen_ip_address") == "127.0.0.1",
    }
    return {"pass": all(checks.values()), "checks": checks}


def systemd_state(user: bool = False) -> dict[str, Any]:
    base = ["systemctl", "--user"] if user else ["systemctl"]
    show = run([*base, "show", SYSTEM_SERVICE, "--property=LoadState,ActiveState,SubState,MainPID", "--no-page"])
    data = {"available": show.returncode == 0, "loaded": False, "active": False, "substate": "", "main_pid": ""}
    if show.returncode != 0:
        return data
    for line in show.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == "LoadState":
            data["loaded"] = value == "loaded"
        elif key == "ActiveState":
            data["active_state"] = value
            data["active"] = value == "active"
        elif key == "SubState":
            data["substate"] = value
        elif key == "MainPID":
            data["main_pid"] = value
    return data


def ps_rows() -> list[dict[str, str]]:
    proc = run(["ps", "-eo", "pid,ppid,args"])
    rows: list[dict[str, str]] = []
    for line in proc.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        rows.append({"pid": parts[0], "ppid": parts[1], "args": parts[2]})
    return rows


def matching_freqtrade_processes() -> list[dict[str, str]]:
    rows = []
    for row in ps_rows():
        args = row["args"]
        if "freqtrade" not in args or " trade" not in f" {args} ":
            continue
        if not any(str(config_path) in args for config_path in ALLOWED_DRY_RUN_CONFIGS):
            continue
        if "config.testnet.local.json" in args:
            continue
        rows.append(row)
    return rows


def active_config_path(processes: list[dict[str, str]]) -> Path:
    for row in processes:
        for config_path in ALLOWED_DRY_RUN_CONFIGS:
            if str(config_path) in row["args"]:
                return config_path
    return RUNTIME_CONFIG


def pair_count(config_path: Path) -> int:
    if not config_path.exists():
        return 0
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return len((cfg.get("exchange") or {}).get("pair_whitelist") or [])


def pid_file_state() -> dict[str, Any]:
    if not PID_FILE.exists():
        return {"exists": False, "running": False, "pid": ""}
    pid = PID_FILE.read_text(encoding="utf-8", errors="ignore").strip()
    running = bool(pid) and run(["kill", "-0", pid]).returncode == 0
    return {"exists": True, "running": running, "pid": pid}


def windows_wsl_carrier_hint() -> dict[str, Any]:
    include_terms = ("start-native-windows.ps1", "start-native.sh", "run-native.sh", "freqtrade trade")
    exclude_terms = ("status-native", "dry_run_status.py", "ensure-dry-run-running", "run-daily-ops", "gatekeeper")
    rows = []
    for row in ps_rows():
        args = row["args"].lower()
        if "wsl.exe" in args and any(term in args for term in include_terms) and not any(term in args for term in exclude_terms):
            rows.append(row)
    windows_rows = []
    powershell = run([
        "powershell.exe",
        "-NoProfile",
        "-Command",
        (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -match 'wsl|wslhost|WindowsTerminal|powershell|pwsh' -and "
            "($_.CommandLine -match 'start-native-windows.ps1|start-native.sh|run-native.sh|freqtrade trade') -and "
            "($_.CommandLine -notmatch 'status-native|dry_run_status.py|ensure-dry-run-running|run-daily-ops|gatekeeper') } | "
            "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
        ),
    ])
    if powershell.returncode == 0 and powershell.stdout.strip():
        try:
            data = json.loads(powershell.stdout)
            if isinstance(data, dict):
                data = [data]
            for item in data or []:
                command_line = str(item.get("CommandLine") or "")
                safe_line = command_line.replace(str(PROJECT_ROOT), "<PROJECT_ROOT>")
                windows_rows.append({
                    "pid": str(item.get("ProcessId") or ""),
                    "name": str(item.get("Name") or ""),
                    "command_line": safe_line[:500],
                })
        except json.JSONDecodeError:
            pass
    return {"detected": bool(rows or windows_rows), "processes": rows, "windows_processes": windows_rows}


def api_health_hint() -> dict[str, Any]:
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8080/api/v1/ping", timeout=2) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
            return {"reachable": resp.status == 200, "status": resp.status, "body": text[:120]}
    except Exception as exc:
        return {"reachable": False, "error": type(exc).__name__}


def dry_run_status() -> dict[str, Any]:
    systemd = systemd_state(False)
    user_systemd = systemd_state(True)
    pid_state = pid_file_state()
    processes = matching_freqtrade_processes()
    active_config = active_config_path(processes)
    safety = load_runtime_safety(active_config)
    windows_hint = windows_wsl_carrier_hint()
    api_hint = api_health_hint()

    running_mode = "none"
    running = False
    if systemd.get("active"):
        running = True
        running_mode = "systemd_system_service"
    elif user_systemd.get("active"):
        running = True
        running_mode = "systemd_user_service"
    elif processes:
        running = True
        running_mode = "freqtrade_trade_process"
    elif pid_state.get("running"):
        running = True
        running_mode = "pid_file_process"
    elif windows_hint.get("detected") and api_hint.get("reachable"):
        running = True
        running_mode = "hidden_windows_wsl_carrier"

    if running and not safety["pass"]:
        status = "DRY_RUN_UNSAFE"
    elif running:
        status = "RUNNING"
    else:
        status = "DRY_RUN_STOPPED"

    return {
        "status": status,
        "running": running,
        "running_mode": running_mode,
        "forward_evidence_blocked": not running,
        "safety": safety,
        "systemd_system": systemd,
        "systemd_user": user_systemd,
        "pid_file": pid_state,
        "freqtrade_trade_processes": processes,
        "hidden_windows_wsl_carrier": windows_hint,
        "api_health": api_hint,
        "runtime_config": str(RUNTIME_CONFIG),
        "active_config": str(active_config),
        "active_pair_count": pair_count(active_config),
        "log_file": str(LOG_FILE),
    }


def print_human(status: dict[str, Any]) -> None:
    print(f"Dry-run running: {status['running']}")
    print(f"Dry-run status: {status['status']}")
    print(f"Dry-run mode: {status['running_mode']}")
    print(f"Forward evidence blocked: {status['forward_evidence_blocked']}")
    print(f"Systemd system: loaded={status['systemd_system'].get('loaded')} active={status['systemd_system'].get('active')} substate={status['systemd_system'].get('substate')}")
    print(f"Systemd user: loaded={status['systemd_user'].get('loaded')} active={status['systemd_user'].get('active')} substate={status['systemd_user'].get('substate')}")
    print(f"Freqtrade trade processes: {len(status['freqtrade_trade_processes'])}")
    print(f"Hidden Windows wsl.exe carrier detected: {status['hidden_windows_wsl_carrier']['detected']}")
    print(f"API health reachable: {status['api_health'].get('reachable')}")


if __name__ == "__main__":
    result = dry_run_status()
    if "--json" in os.sys.argv:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_human(result)
    raise SystemExit(0 if result["running"] and result["safety"]["pass"] else 2)
