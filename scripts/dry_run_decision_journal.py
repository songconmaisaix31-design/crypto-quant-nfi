#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
REPORT_DIR = PROJECT_ROOT / "reports/dry_run_journal"
JOURNAL_CSV = REPORT_DIR / "dry_run_decision_journal.csv"
REPORT_MD = REPORT_DIR / "dry_run_journal_report.md"
SUMMARY_JSON = REPORT_DIR / "dry_run_journal_summary.json"
LATEST_MARKET = PROJECT_ROOT / "user_data/market_state/market_state_latest.json"
DECISION_SUMMARY = PROJECT_ROOT / "reports/decision_engine/decision_engine_summary.json"
DRYRUN_DB = PROJECT_ROOT / "user_data/tradesv3.dryrun.sqlite"
DRYRUN_LOG = PROJECT_ROOT / "user_data/logs/freqtrade-native.log"


FIELDS = [
    "timestamp",
    "bot_status",
    "market_date",
    "market_sentiment_score",
    "primary_regime",
    "regime_tags",
    "decision_engine_available",
    "last_offline_allowed_signals",
    "last_offline_blocked_signals",
    "open_trades",
    "total_dry_run_trades",
    "total_dry_run_orders",
    "recent_log_signal_count",
    "recent_log_trade_count",
    "decision_action",
    "stake_multiplier",
    "consistency_status",
    "notes",
]


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def safety() -> dict[str, bool]:
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
    if not all(checks.values()):
        raise RuntimeError(f"Unsafe runtime config: {checks}")
    return checks


def status() -> str:
    try:
        proc = subprocess.run(["bash", str(PROJECT_ROOT / "scripts/status-native.sh")], cwd=PROJECT_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        for line in proc.stdout.splitlines():
            if line.startswith("Status:"):
                return line.replace("Status:", "").strip()
        return "unknown"
    except Exception as exc:
        return f"status_error:{exc!r}"


def db_counts() -> dict[str, int]:
    out = {"open_trades": 0, "total_dry_run_trades": 0, "total_dry_run_orders": 0}
    if not DRYRUN_DB.exists():
        return out
    try:
        con = sqlite3.connect(DRYRUN_DB)
        cur = con.cursor()
        out["open_trades"] = int(cur.execute("select count(*) from trades where is_open = 1").fetchone()[0])
        out["total_dry_run_trades"] = int(cur.execute("select count(*) from trades").fetchone()[0])
        out["total_dry_run_orders"] = int(cur.execute("select count(*) from orders").fetchone()[0])
    except Exception:
        pass
    return out


def log_counts() -> dict[str, int]:
    if not DRYRUN_LOG.exists():
        return {"recent_log_signal_count": 0, "recent_log_trade_count": 0}
    lines = DRYRUN_LOG.read_text(encoding="utf-8", errors="ignore").splitlines()[-500:]
    signal_terms = ("enter_long", "entry signal", "Found open trade", "create_trade", "Executing Buy")
    trade_terms = ("dry_run", "order", "buy", "sell", "trade")
    return {
        "recent_log_signal_count": sum(1 for line in lines if any(t.lower() in line.lower() for t in signal_terms)),
        "recent_log_trade_count": sum(1 for line in lines if any(t.lower() in line.lower() for t in trade_terms)),
    }


def append_row(row: dict[str, Any]) -> None:
    exists = JOURNAL_CSV.exists()
    with JOURNAL_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in FIELDS})


def read_rows() -> list[dict[str, str]]:
    if not JOURNAL_CSV.exists():
        return []
    with JOURNAL_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    before = RUNTIME_CONFIG.read_bytes()
    safe = safety()
    market = load_json(LATEST_MARKET, {})
    decision = load_json(DECISION_SUMMARY, {})
    counts = db_counts()
    logs = log_counts()
    signal_count = logs["recent_log_signal_count"]
    order_count = counts["total_dry_run_orders"]
    consistency = "inconclusive_no_new_signal_or_fill"
    if signal_count > 0 and order_count > 0:
        consistency = "needs_manual_reconciliation"
    elif signal_count > 0 and order_count == 0:
        consistency = "signal_seen_no_fill_seen"
    row = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "bot_status": status(),
        "market_date": market.get("date", ""),
        "market_sentiment_score": market.get("market_sentiment_score", ""),
        "primary_regime": market.get("primary_regime", ""),
        "regime_tags": market.get("regime_tags", ""),
        "decision_engine_available": bool(decision),
        "last_offline_allowed_signals": decision.get("allowed_signals", ""),
        "last_offline_blocked_signals": decision.get("blocked_signals", ""),
        "decision_action": "journal_only_no_live_signal_decision",
        "stake_multiplier": "",
        "consistency_status": consistency,
        "notes": "Append-only journal. No config changes and no live orders.",
    }
    row.update(counts)
    row.update(logs)
    append_row(row)
    rows = read_rows()
    summary = {
        "safe_config": safe,
        "runtime_config_untouched": before == RUNTIME_CONFIG.read_bytes(),
        "journal_rows": len(rows),
        "latest_row": row,
        "decision_fill_consistency_proven": False,
        "reason": "Journal framework exists, but consistency is not proven until real dry-run signal/fill pairs are observed over time.",
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    lines = [
        "# Dry-Run Decision Journal",
        "",
        "This is append-only evidence. It does not modify trading config and does not place orders.",
        "",
        f"- Journal rows: `{len(rows)}`",
        f"- Bot status: `{row['bot_status']}`",
        f"- Latest market regime: `{row['primary_regime']}`",
        f"- Open trades: `{row['open_trades']}`",
        f"- Total dry-run trades: `{row['total_dry_run_trades']}`",
        f"- Total dry-run orders: `{row['total_dry_run_orders']}`",
        f"- Consistency status: `{row['consistency_status']}`",
        "",
        "Current consistency evidence is not sufficient to pass the pre-live gate.",
    ]
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[PASS] appended {JOURNAL_CSV}")
    print(f"[PASS] wrote {REPORT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
