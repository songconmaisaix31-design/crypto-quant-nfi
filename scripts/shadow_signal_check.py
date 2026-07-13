#!/usr/bin/env python3
from __future__ import annotations

import base64
import csv
import datetime as dt
import io
import json
import os
import pickle
import re
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any
import urllib.request


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
STRATEGY_FILE = PROJECT_ROOT / "user_data/strategies/NostalgiaForInfinityX7.py"
DRYRUN_DB = PROJECT_ROOT / "user_data/tradesv3.dryrun.sqlite"
LOG_DIR = PROJECT_ROOT / "user_data/logs"
REPORT_OUT = PROJECT_ROOT / "reports/shadow_decision"
USER_OUT = PROJECT_ROOT / "user_data/shadow_decision"
CHECK_CSV = REPORT_OUT / "shadow_signal_check.csv"
CHECK_REPORT = REPORT_OUT / "shadow_signal_check_report.md"
CHECK_LOG = REPORT_OUT / "shadow_signal_check.log"
SNAPSHOT = USER_OUT / "latest_signal_snapshot.json"
SHADOW_SNAPSHOT = USER_OUT / "latest_shadow_snapshot.json"
REPLAY_EXPORT = REPORT_OUT / "shadow_signal_replay_latest.zip"
DATA_DIR = PROJECT_ROOT / "user_data/data/binance"

FIELDS = [
    "pair",
    "timeframe",
    "latest_candle_time",
    "candles_available",
    "startup_candle_count",
    "signal_check_status",
    "enter_long_detected",
    "enter_tag",
    "signal_time",
    "notes",
]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def safety_check() -> dict[str, Any]:
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
    return {"pass": all(checks.values()), "checks": checks, "config": cfg}


def freqtrade_bin() -> str:
    env_bin = os.environ.get("FREQTRADE_BIN")
    if env_bin and Path(env_bin).exists():
        return env_bin
    sibling = Path(sys.executable).with_name("freqtrade")
    if sibling.exists():
        return str(sibling)
    return "freqtrade"


def api_request(cfg: dict[str, Any], endpoint: str, timeout: float = 2.0) -> tuple[bool, Any, str]:
    api = cfg.get("api_server", {})
    host = api.get("listen_ip_address") or "127.0.0.1"
    port = api.get("listen_port") or 8080
    req = urllib.request.Request(f"http://{host}:{port}{endpoint}")
    username = api.get("username")
    password = api.get("password")
    if username and password:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
            try:
                return True, json.loads(text), ""
            except json.JSONDecodeError:
                return True, text, ""
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}"


def db_rows(table: str) -> list[dict[str, Any]]:
    if not DRYRUN_DB.exists():
        return []
    try:
        con = sqlite3.connect(DRYRUN_DB)
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(f"select * from {table}").fetchall()]
    except Exception:
        return []


def latest_log_events() -> dict[str, Any]:
    errors: list[str] = []
    signal_lines: list[str] = []
    readable = False
    for path in sorted(LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]:
        readable = True
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-1200:]:
            low = line.lower()
            if any(term in low for term in ("buy signal", "entry signal", "enter_long", "signal found", "found open trade")):
                signal_lines.append(line[-240:])
            if any(term in low for term in ("error", "exception", "warning", "exchange not available", "rejected")):
                errors.append(line[-240:])
    return {"readable": readable, "signal_lines": signal_lines[-20:], "errors": errors[-30:]}


def strategy_startup_count() -> int:
    if not STRATEGY_FILE.exists():
        return 0
    text = STRATEGY_FILE.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"startup_candle_count\s*=\s*(\d+)", text)
    return int(match.group(1)) if match else 0


def load_candle_row(pair: str, timeframe: str, startup: int) -> dict[str, Any]:
    file_name = pair.replace("/", "_").replace(":", "_") + f"-{timeframe}.feather"
    path = DATA_DIR / file_name
    row = {
        "pair": pair,
        "timeframe": timeframe,
        "latest_candle_time": "",
        "candles_available": 0,
        "startup_candle_count": startup,
        "signal_check_status": "data_unavailable",
        "enter_long_detected": False,
        "enter_tag": "",
        "signal_time": "",
        "notes": f"missing data file: {path}",
    }
    if not path.exists():
        return row
    try:
        import pandas as pd

        df = pd.read_feather(path)
        row["candles_available"] = len(df)
        if len(df):
            date_col = "date" if "date" in df.columns else df.columns[0]
            row["latest_candle_time"] = str(df.iloc[-1][date_col])
        if startup and len(df) < startup:
            row["signal_check_status"] = "insufficient_candles"
            row["notes"] = f"candles {len(df)} < startup {startup}"
        else:
            row["signal_check_status"] = "ready_for_replay"
            row["notes"] = "data present; waiting for replay result"
    except Exception as exc:
        row["notes"] = f"data read failed: {type(exc).__name__}: {exc}"
    return row


def strategy_load_check(log: list[str]) -> tuple[bool, str]:
    cmd = [
        freqtrade_bin(),
        "list-strategies",
        "--config",
        str(RUNTIME_CONFIG),
        "--userdir",
        str(PROJECT_ROOT / "user_data"),
        "--strategy-path",
        str(PROJECT_ROOT / "user_data/strategies"),
    ]
    try:
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=90)
        log.append("$ " + " ".join(cmd))
        log.append(proc.stdout[-4000:])
        if proc.stderr:
            log.append(proc.stderr[-4000:])
        ok = proc.returncode == 0 and "NostalgiaForInfinityX7" in proc.stdout
        return ok, "" if ok else f"strategy list failed rc={proc.returncode}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def replay_signals(rows: list[dict[str, Any]], log: list[str]) -> tuple[str, dict[str, dict[str, Any]], str]:
    ready_rows = [r for r in rows if r["signal_check_status"] == "ready_for_replay"]
    if not ready_rows:
        return "insufficient_candles", {}, "no pair has enough candles for replay"
    latest_dates = [str(r["latest_candle_time"])[:10] for r in ready_rows if r.get("latest_candle_time")]
    if not latest_dates:
        return "data_unavailable", {}, "latest candle time unavailable"
    end_date = max(latest_dates)
    try:
        end = dt.date.fromisoformat(end_date)
    except ValueError:
        return "data_unavailable", {}, f"invalid latest candle date {end_date}"
    start = end - dt.timedelta(days=4)
    timerange = f"{start:%Y%m%d}-{(end + dt.timedelta(days=1)):%Y%m%d}"
    if REPLAY_EXPORT.exists():
        REPLAY_EXPORT.unlink()
    cmd = [
        freqtrade_bin(),
        "backtesting",
        "--config",
        str(RUNTIME_CONFIG),
        "--userdir",
        str(PROJECT_ROOT / "user_data"),
        "--strategy",
        "NostalgiaForInfinityX7",
        "--strategy-path",
        str(PROJECT_ROOT / "user_data/strategies"),
        "--timerange",
        timerange,
        "--export",
        "signals",
        "--export-directory",
        str(REPORT_OUT),
        "--export-filename",
        str(REPLAY_EXPORT),
    ]
    run_started = dt.datetime.now().timestamp()
    try:
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=240)
        log.append("$ " + " ".join(cmd))
        log.append(proc.stdout[-6000:])
        if proc.stderr:
            log.append(proc.stderr[-6000:])
        if proc.returncode != 0:
            return "data_unavailable", {}, f"replay failed rc={proc.returncode}"
    except Exception as exc:
        return "data_unavailable", {}, f"replay exception: {type(exc).__name__}: {exc}"
    if not REPLAY_EXPORT.exists():
        candidates = list(REPORT_OUT.glob("*.zip")) + list((PROJECT_ROOT / "user_data/backtest_results").glob("*.zip"))
        recent = [p for p in candidates if p.stat().st_mtime >= run_started - 5]
        zips = sorted(recent or candidates, key=lambda p: p.stat().st_mtime)
        zip_path = zips[-1] if zips else None
    else:
        zip_path = REPLAY_EXPORT
    if not zip_path:
        return "data_unavailable", {}, "replay did not create export zip"
    try:
        import pandas as pd  # noqa: F401

        found: dict[str, dict[str, Any]] = {}
        with zipfile.ZipFile(zip_path) as zf:
            signal_files = [n for n in zf.namelist() if n.endswith("_signals.pkl")]
            if not signal_files:
                return "confirmed_no_signal", {}, "replay completed; signals export has no signals pkl"
            obj = pickle.loads(zf.read(signal_files[0]))
            strategy_obj = obj.get("NostalgiaForInfinityX7", obj) if isinstance(obj, dict) else {}
            for pair, df in strategy_obj.items():
                if not hasattr(df, "columns") or "enter_long" not in df.columns:
                    continue
                sig = df[df["enter_long"].fillna(0).astype(float) > 0]
                if len(sig):
                    last = sig.iloc[-1]
                    found[pair] = {
                        "signal_time": str(last.get("date", "")),
                        "enter_tag": str(last.get("enter_tag", "")),
                        "count": len(sig),
                    }
        return ("confirmed_signal" if found else "confirmed_no_signal"), found, f"replay zip={zip_path}"
    except Exception as exc:
        return "data_unavailable", {}, f"signal parse failed: {type(exc).__name__}: {exc}"


def write_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Shadow Signal Check Report",
        "",
        f"Generated: `{summary['generated_at']}`",
        "",
        "This check is read-only. It does not place orders, write API keys, or modify strategy/config files.",
        "",
        "## Summary",
        f"- signal_detection_status: `{summary['signal_detection_status']}`",
        f"- signal_check_method: `{summary['signal_check_method']}`",
        f"- confirmed_signal_count: `{summary['confirmed_signal_count']}`",
        f"- confirmed_no_signal_count: `{summary['confirmed_no_signal_count']}`",
        f"- inferred_signal_count: `{summary['inferred_signal_count']}`",
        f"- open_trades_count: `{summary['open_trades_count']}`",
        f"- new_trade_since_last_snapshot: `{summary['new_trade_since_last_snapshot']}`",
        f"- strategy_load_status: `{summary['strategy_load_status']}`",
        "",
        "## Pair Checks",
        "| pair | timeframe | latest candle | candles | status | enter_long | enter_tag | notes |",
        "|---|---|---|---:|---|---|---|---|",
    ]
    for row in rows:
        lines.append(f"| `{row['pair']}` | `{row['timeframe']}` | `{row['latest_candle_time']}` | {row['candles_available']} | `{row['signal_check_status']}` | `{row['enter_long_detected']}` | `{row['enter_tag']}` | {row['notes']} |")
    CHECK_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    REPORT_OUT.mkdir(parents=True, exist_ok=True)
    USER_OUT.mkdir(parents=True, exist_ok=True)
    log: list[str] = [f"generated_at={now()}", f"project={PROJECT_ROOT}"]
    before = RUNTIME_CONFIG.read_bytes() if RUNTIME_CONFIG.exists() else b""
    safe = safety_check()
    if not safe["pass"]:
        summary = {"generated_at": now(), "safe_config": False, "safety_checks": safe["checks"], "signal_detection_status": "data_unavailable", "blocked": True}
        SNAPSHOT.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        CHECK_LOG.write_text("BLOCKED unsafe runtime config\n" + json.dumps(safe["checks"], indent=2) + "\n", encoding="utf-8")
        print("[BLOCKED] unsafe runtime config")
        return 2
    cfg = safe["config"]
    pairs = cfg.get("exchange", {}).get("pair_whitelist", [])
    timeframe = cfg.get("timeframe") or "5m"
    startup = int(cfg.get("startup_candle_count") or strategy_startup_count() or 0)
    api_count_ok, api_count, api_count_err = api_request(cfg, "/api/v1/count")
    trades = db_rows("trades")
    orders = db_rows("orders")
    previous = load_json(SNAPSHOT, load_json(SHADOW_SNAPSHOT, {}))
    previous_ids = {str(x) for x in previous.get("seen_trade_ids", [])}
    current_ids = {str(t.get("id")) for t in trades}
    new_trade_ids = sorted(current_ids - previous_ids)
    log_events = latest_log_events()
    rows = [load_candle_row(pair, timeframe, startup) for pair in pairs]
    strategy_ok, strategy_err = strategy_load_check(log)
    inferred_count = len(new_trade_ids)
    method = "db_api_log"
    status = "inferred_from_trade" if inferred_count else "confirmed_no_trade_but_signal_unknown"
    notes = ""
    confirmed: dict[str, dict[str, Any]] = {}
    if inferred_count:
        notes = f"new dry-run trade ids: {','.join(new_trade_ids)}"
    elif not log_events["readable"] and not api_count_ok and not DRYRUN_DB.exists():
        status = "data_unavailable"
        notes = "no readable logs, API, or dry-run DB"
    elif not strategy_ok:
        status = "strategy_load_failed"
        notes = strategy_err
    elif any(r["signal_check_status"] == "insufficient_candles" for r in rows):
        status = "insufficient_candles"
        notes = "one or more pairs do not satisfy startup candle count"
    else:
        method = "freqtrade_backtesting_signal_replay"
        status, confirmed, notes = replay_signals(rows, log)
    for row in rows:
        if row["pair"] in confirmed:
            row["signal_check_status"] = "confirmed_signal"
            row["enter_long_detected"] = True
            row["enter_tag"] = confirmed[row["pair"]].get("enter_tag", "")
            row["signal_time"] = confirmed[row["pair"]].get("signal_time", "")
            row["notes"] = f"confirmed enter_long count={confirmed[row['pair']].get('count')}"
        elif row["signal_check_status"] == "ready_for_replay":
            if status == "confirmed_no_signal":
                row["signal_check_status"] = "confirmed_no_signal"
                row["notes"] = notes
            elif status in ("strategy_load_failed", "data_unavailable"):
                row["signal_check_status"] = status
                row["notes"] = notes
            else:
                row["signal_check_status"] = status
                row["notes"] = notes
    confirmed_signal_count = len(confirmed)
    confirmed_no_signal_count = sum(1 for r in rows if r["signal_check_status"] == "confirmed_no_signal")
    summary = {
        "generated_at": now(),
        "safe_config": True,
        "safety_checks": safe["checks"],
        "runtime_config_untouched": before == (RUNTIME_CONFIG.read_bytes() if RUNTIME_CONFIG.exists() else b""),
        "signal_detection_status": status,
        "signal_check_method": method,
        "confirmed_signal_count": confirmed_signal_count,
        "confirmed_no_signal_count": confirmed_no_signal_count,
        "inferred_signal_count": inferred_count,
        "open_trades_count": sum(1 for t in trades if t.get("is_open")),
        "recent_closed_trades_count": sum(1 for t in trades if not t.get("is_open")),
        "recent_orders_count": len(orders),
        "new_trade_since_last_snapshot": inferred_count,
        "strategy_load_status": "ok" if strategy_ok else "failed",
        "strategy_load_error": strategy_err,
        "api_count_available": api_count_ok,
        "api_count_error": api_count_err,
        "log_readable": log_events["readable"],
        "log_signal_lines_count": len(log_events["signal_lines"]),
        "recent_errors_count": len(log_events["errors"]),
        "pairs_checked": pairs,
        "timeframe": timeframe,
        "startup_candle_count": startup,
        "confirmed_signals": confirmed,
        "seen_trade_ids": sorted(current_ids),
        "notes": notes,
    }
    write_csv(CHECK_CSV, rows, FIELDS)
    write_report(summary, rows)
    SNAPSHOT.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log += [
        f"signal_detection_status={status}",
        f"signal_check_method={method}",
        f"confirmed_signal_count={confirmed_signal_count}",
        f"confirmed_no_signal_count={confirmed_no_signal_count}",
        f"inferred_signal_count={inferred_count}",
        f"notes={notes}",
    ]
    CHECK_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")
    for line in log:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
