#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
SECRET_KEYS = ("key", "secret", "password", "token", "signature", "api_key", "private_key", "access_token", "webhook")
RISK_TERMS = ("fapi", "dapi", "sapi", "futures", "margin", "leverage", "short")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def local_now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def run_cmd(cmd: list[str], timeout: int = 120) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=timeout)
        return {
            "command": " ".join(cmd),
            "exit_code": proc.returncode,
            "stdout": redact_text(proc.stdout),
            "stderr": redact_text(proc.stderr),
            "status": "PASS" if proc.returncode == 0 else "FAIL",
        }
    except subprocess.TimeoutExpired as exc:
        return {"command": " ".join(cmd), "exit_code": 124, "stdout": redact_text(exc.stdout or ""), "stderr": "timeout", "status": "TIMEOUT"}
    except Exception as exc:
        return {"command": " ".join(cmd), "exit_code": 1, "stdout": "", "stderr": redact_text(repr(exc)), "status": "ERROR"}


def git_info() -> dict[str, str]:
    def get(args: list[str]) -> str:
        proc = subprocess.run(["git", *args], cwd=PROJECT_ROOT, text=True, capture_output=True)
        return proc.stdout.strip() if proc.returncode == 0 else ""

    return {
        "branch": get(["branch", "--show-current"]) or "unknown",
        "commit": get(["rev-parse", "--short", "HEAD"]) or "unknown",
        "commit_full": get(["rev-parse", "HEAD"]) or "unknown",
    }


def redact_text(text: str) -> str:
    value = text or ""
    for word in ("BINANCE_TESTNET_KEY", "BINANCE_TESTNET_SECRET"):
        value = value.replace(word, f"{word[:4]}***")
    value = re.sub(r"(?i)(api[_-]?key|secret|password|token|signature|private[_-]?key)(['\"\s:=]+)([A-Za-z0-9_./+=:-]{8,})", r"\1\2[REDACTED]", value)
    value = re.sub(r"\b(sk-[A-Za-z0-9_-]{8,})\b", "sk-***", value)
    value = re.sub(r"\b(AKIA[A-Z0-9]{8,})\b", "AKIA***", value)
    return value


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if any(term in key.lower() for term in SECRET_KEYS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_value(item)
        return redacted
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def runtime_safety() -> dict[str, Any]:
    cfg = load_json(RUNTIME_CONFIG, {})
    ex = cfg.get("exchange", {}) if isinstance(cfg, dict) else {}
    api = cfg.get("api_server", {}) if isinstance(cfg, dict) else {}
    text = json.dumps(redact_value(cfg), ensure_ascii=False).lower() if isinstance(cfg, dict) else ""
    checks = {
        "dry_run": cfg.get("dry_run") is True,
        "trading_mode_spot": cfg.get("trading_mode") == "spot",
        "margin_mode_empty": cfg.get("margin_mode") in ("", None),
        "can_short_false": cfg.get("can_short") is False,
        "exchange_credentials_empty": not any(ex.get(k) for k in ("key", "secret", "password")),
        "api_localhost": api.get("listen_ip_address") == "127.0.0.1",
        "no_risky_runtime_terms": not any(term in text for term in ("futures", "leverage", "fapi", "dapi")),
    }
    return {"pass": all(checks.values()), "checks": checks}


def testnet_config_safe() -> dict[str, Any]:
    path = PROJECT_ROOT / "user_data/config.testnet.local.json"
    cfg = load_json(path, {})
    ex = cfg.get("exchange", {}) if isinstance(cfg, dict) else {}
    text = json.dumps(redact_value(cfg), ensure_ascii=False).lower() if isinstance(cfg, dict) else ""
    checks = {
        "exists": path.exists(),
        "separate_from_runtime": path != RUNTIME_CONFIG,
        "spot": cfg.get("trading_mode") == "spot",
        "margin_empty": cfg.get("margin_mode") in ("", None),
        "can_short_false": cfg.get("can_short") is False,
        "credentials_empty": not any(ex.get(k) for k in ("key", "secret", "password")),
        "testnet_endpoint": "testnet.binance.vision" in text,
        "no_mainnet_endpoint": "api.binance.com" not in text,
        "no_fapi_dapi": "fapi" not in text and "dapi" not in text,
    }
    return {"pass": all(checks.values()), "checks": checks}


def read_status(path: Path) -> str:
    data = load_json(path, {})
    if isinstance(data, dict):
        for key in ("status", "gatekeeper_status", "micro_live_status", "pre_live_status"):
            if data.get(key):
                return str(data[key])
        if data.get("live_trading_blocked") is True:
            return "BLOCKED"
        if data.get("testnet_allowed") is True:
            return "TESTNET_ALLOWED"
    return "MISSING"


def append_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as f:
        f.write(text)


def phase_record(phase: str, status: str, message: str, evidence: dict[str, Any] | None = None) -> None:
    out = PROJECT_ROOT / "reports/ops_hardening"
    ensure_dir(out)
    record = {
        "timestamp_utc": utc_now(),
        "phase": phase,
        "status": status,
        "message": message,
        "evidence": evidence or {},
    }
    append_text(out / "phase_log.md", f"- `{record['timestamp_utc']}` `{phase}` `{status}` - {message}\n")
    summary_path = out / "phase_summary.json"
    summary = load_json(summary_path, {"phases": []})
    summary.setdefault("phases", []).append(record)
    summary["latest_status"] = status
    summary["latest_phase"] = phase
    summary["updated_at"] = utc_now()
    write_json(summary_path, summary)

