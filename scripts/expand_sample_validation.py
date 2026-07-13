#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import argparse
import io
import json
import os
import pickle
import re
import shlex
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
SAMPLE_CONFIG = PROJECT_ROOT / "user_data/config.sample_validation.json"
REPORT_DIR = PROJECT_ROOT / "reports/sample_validation"
EXPORT_DIR = REPORT_DIR / "exports"
REPORT_MD = REPORT_DIR / "sample_validation_report.md"
SUMMARY_JSON = REPORT_DIR / "sample_validation_summary.json"
SIGNAL_CSV = REPORT_DIR / "sample_signal_matrix.csv"
BACKTEST_CSV = REPORT_DIR / "sample_backtest_matrix.csv"
LOG_TXT = REPORT_DIR / "sample_validation_logs.txt"
STRATEGY_NAME = "NostalgiaForInfinityX7"
BASE_PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT"]
PREFERRED_EXPANDED = [
    "BTC/USDT",
    "ETH/USDT",
    "BNB/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "ADA/USDT",
    "DOGE/USDT",
    "TRX/USDT",
    "LINK/USDT",
    "AVAX/USDT",
    "SUI/USDT",
    "XLM/USDT",
    "BCH/USDT",
    "LTC/USDT",
    "DOT/USDT",
    "UNI/USDT",
    "NEAR/USDT",
    "APT/USDT",
    "ICP/USDT",
    "FIL/USDT",
]
TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]
TF_MINUTES = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
DOWNLOAD_DAYS = 1200
RISK_WORDS = ("fapi", "dapi", "futures", "margin", "short", "leverage")
STABLE_BASES = {"USDC", "FDUSD", "TUSD", "BUSD", "DAI", "PAX", "USDP", "EUR", "AEUR", "TRY", "BRL", "USD"}
LEVERAGED_PARTS = ("UP", "DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S")


class Recorder:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def log(self, line: str = "") -> None:
        self.lines.append(line)
        print(line)

    def section(self, title: str) -> None:
        self.log(f"\n=== {title} ===")

    def write(self) -> None:
        LOG_TXT.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def run_cmd(cmd: list[str], rec: Recorder, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    rec.log("$ " + " ".join(shlex.quote(x) for x in cmd))
    proc = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=timeout,
    )
    if proc.stdout:
        rec.log(proc.stdout[-14000:].rstrip())
    rec.log(f"[exit] {proc.returncode}")
    return proc


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_runtime_safety(cfg: dict[str, Any], label: str, rec: Recorder) -> dict[str, Any]:
    ex = cfg.get("exchange", {})
    api = cfg.get("api_server", {})
    checks = {
        "dry_run": cfg.get("dry_run") is True,
        "trading_mode_spot": cfg.get("trading_mode") == "spot",
        "margin_mode_empty": cfg.get("margin_mode") in ("", None),
        "can_short_false": cfg.get("can_short") is False,
        "exchange_credentials_empty": not (ex.get("key") or ex.get("secret") or ex.get("password")),
        "api_localhost": api.get("listen_ip_address") == "127.0.0.1",
    }
    enabled_risks = []
    if cfg.get("trading_mode") not in ("spot", None):
        enabled_risks.append(f"trading_mode={cfg.get('trading_mode')}")
    if cfg.get("margin_mode") not in ("", None):
        enabled_risks.append(f"margin_mode={cfg.get('margin_mode')}")
    if cfg.get("can_short") is True:
        enabled_risks.append("can_short=True")
    rec.section(f"Safety check: {label}")
    for key, value in checks.items():
        rec.log(f"{key}: {value}")
    rec.log("enabled risk settings: " + (", ".join(enabled_risks) if enabled_risks else "none"))
    if not all(checks.values()) or enabled_risks:
        raise RuntimeError(f"Unsafe config at {label}: checks={checks}, enabled_risks={enabled_risks}")
    return {"checks": checks, "enabled_risks": enabled_risks}


def strategy_metadata() -> dict[str, Any]:
    path = PROJECT_ROOT / "vendor/NostalgiaForInfinity/NostalgiaForInfinityX7.py"
    text = path.read_text(encoding="utf-8", errors="ignore")
    meta: dict[str, Any] = {"path": str(path), "timeframe": "5m", "startup_candle_count": 800, "info_timeframes": ["15m", "1h", "4h", "1d"], "btc_info_timeframes": ["1h", "4h", "1d"]}
    match = re.search(r"^\s*timeframe\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
    if match:
        meta["timeframe"] = match.group(1)
    match = re.search(r"^\s*startup_candle_count\s*:?.*=\s*([0-9]+)", text, re.M)
    if match:
        meta["startup_candle_count"] = int(match.group(1))
    for key in ("info_timeframes", "btc_info_timeframes"):
        match = re.search(rf"^\s*{key}\s*=\s*(\[[^\]]*\])", text, re.M)
        if match:
            meta[key] = re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))
    return meta


def is_plain_usdt_spot(symbol: str, market: dict[str, Any]) -> bool:
    if not symbol.endswith("/USDT"):
        return False
    if not market.get("spot"):
        return False
    if market.get("active") is False:
        return False
    base = str(market.get("base") or symbol.split("/")[0])
    if base in STABLE_BASES:
        return False
    if any(base.endswith(part) for part in LEVERAGED_PARTS):
        return False
    if any(part in base for part in ("BULL", "BEAR")):
        return False
    return True


def generate_expanded_pairs(cfg: dict[str, Any], rec: Recorder) -> list[str]:
    rec.section("Generate expanded pairlist")
    try:
        import ccxt

        ex_cfg = cfg.get("exchange", {}).get("ccxt_config", {})
        exchange = ccxt.binance(ex_cfg)
        markets = exchange.load_markets()
        tickers = {}
        try:
            tickers = exchange.fetch_tickers()
        except Exception as exc:
            rec.log(f"[WARN] fetch_tickers failed, falling back to preferred list order: {exc!r}")
        scored: list[tuple[float, str]] = []
        for symbol in PREFERRED_EXPANDED:
            market = markets.get(symbol)
            if market and is_plain_usdt_spot(symbol, market):
                quote_volume = 0.0
                ticker = tickers.get(symbol) or {}
                for key in ("quoteVolume", "quote_volume"):
                    if ticker.get(key) is not None:
                        quote_volume = float(ticker[key] or 0)
                        break
                scored.append((quote_volume, symbol))
        if tickers:
            scored.sort(reverse=True)
        pairs = [symbol for _, symbol in scored]
        for pair in PREFERRED_EXPANDED:
            if pair not in pairs and pair in markets and is_plain_usdt_spot(pair, markets[pair]):
                pairs.append(pair)
        pairs = pairs[:20]
        if len(pairs) < 20:
            raise RuntimeError(f"Only {len(pairs)} valid preferred pairs found")
        rec.log("expanded pairs: " + ", ".join(pairs))
        return pairs
    except Exception as exc:
        rec.log(f"[WARN] CCXT pair validation failed, using conservative preferred list: {exc!r}")
        return PREFERRED_EXPANDED[:20]


def write_sample_config(base_cfg: dict[str, Any], pairs: list[str], rec: Recorder) -> None:
    cfg = json.loads(json.dumps(base_cfg))
    ex = cfg.setdefault("exchange", {})
    ex["pair_whitelist"] = pairs
    ex["key"] = ""
    ex["secret"] = ""
    ex["password"] = ""
    ex["enable_ws"] = False
    cfg["dry_run"] = True
    cfg["trading_mode"] = "spot"
    cfg["margin_mode"] = ""
    cfg["can_short"] = False
    api = cfg.setdefault("api_server", {})
    api["listen_ip_address"] = "127.0.0.1"
    cfg.setdefault("pairlists", [{"method": "StaticPairList"}])
    SAMPLE_CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    rec.log(f"[PASS] wrote sample config: {SAMPLE_CONFIG}")


def data_file(pair: str, timeframe: str) -> Path:
    return PROJECT_ROOT / "user_data/data/binance" / f"{pair.replace('/', '_')}-{timeframe}.feather"


def read_ohlcv(path: Path) -> pd.DataFrame:
    return pd.read_feather(path)


def common_data_end(pairs: list[str]) -> dt.date:
    ends = []
    for pair in pairs:
        path = data_file(pair, "5m")
        if path.exists():
            try:
                df = read_ohlcv(path)
                if len(df) and "date" in df.columns:
                    ends.append(pd.to_datetime(df["date"], utc=True).max().date())
            except Exception:
                pass
    return min(ends) if ends else dt.date.today()


def timerange_for(days: int, pairs: list[str]) -> str:
    end = common_data_end(pairs)
    start = end - dt.timedelta(days=days)
    return f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"


def download_data(config_path: Path, pairs: list[str], rec: Recorder) -> int:
    rec.section(f"Download data for {len(pairs)} pairs")
    cmd = [
        "freqtrade",
        "download-data",
        "--config",
        str(config_path),
        "--userdir",
        str(PROJECT_ROOT / "user_data"),
        "--pairs",
        *pairs,
        "--timeframes",
        *TIMEFRAMES,
        "--days",
        str(DOWNLOAD_DAYS),
        "--no-parallel-download",
        "--prepend",
        "--logfile",
        str(REPORT_DIR / "download-data.log"),
    ]
    return run_cmd(cmd, rec, timeout=7200).returncode


def check_data_quality(pairs: list[str], group: str, timerange: str, startup: int) -> list[dict[str, Any]]:
    rows = []
    for pair in pairs:
        for tf in TIMEFRAMES:
            path = data_file(pair, tf)
            row: dict[str, Any] = {
                "group": group,
                "pair": pair,
                "timeframe": tf,
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
                "candles": 0,
                "start": "",
                "end": "",
                "missing_candles": "",
                "gap_count": "",
                "startup_ok": False,
                "enter_long_count": 0,
                "exit_signal_count": 0,
                "enter_tag_top": "",
                "notes": "",
            }
            notes = []
            if not path.exists():
                notes.append("missing file")
            elif row["size_bytes"] <= 0:
                notes.append("empty file")
            else:
                try:
                    df = read_ohlcv(path)
                    row["candles"] = int(len(df))
                    if len(df) == 0:
                        notes.append("empty dataframe")
                    elif "date" not in df.columns:
                        notes.append("missing date column")
                    else:
                        df = df.copy()
                        df["date"] = pd.to_datetime(df["date"], utc=True)
                        df = df.sort_values("date")
                        row["start"] = df["date"].iloc[0].isoformat()
                        row["end"] = df["date"].iloc[-1].isoformat()
                        expected = pd.Timedelta(minutes=TF_MINUTES[tf])
                        gaps = df["date"].diff().dropna()
                        missing = gaps[gaps > expected]
                        row["gap_count"] = int(len(missing))
                        row["missing_candles"] = int(((missing / expected) - 1).sum()) if len(missing) else 0
                        base_need = startup if tf == "5m" else max(1, startup * TF_MINUTES["5m"] // TF_MINUTES[tf])
                        row["startup_ok"] = row["candles"] >= base_need
                        if not row["startup_ok"]:
                            notes.append(f"startup candles insufficient: {row['candles']} < {base_need}")
                        if row["gap_count"]:
                            notes.append(f"gaps detected: {row['gap_count']}")
                except Exception as exc:
                    notes.append(f"read error: {exc!r}")
            row["notes"] = "; ".join(notes)
            rows.append(row)
    return rows


def write_signal_matrix(rows: list[dict[str, Any]]) -> None:
    fields = [
        "group",
        "pair",
        "timeframe",
        "candles",
        "start",
        "end",
        "missing_candles",
        "gap_count",
        "startup_ok",
        "enter_long_count",
        "enter_tag_top",
        "exit_signal_count",
        "notes",
    ]
    with SIGNAL_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def parse_total_trades(stdout: str) -> int:
    matches = re.findall(r"TOTAL\s+\|\s+([0-9]+)\s+\|", stdout)
    return int(matches[-1]) if matches else 0


def parse_backtest_json(
    obj: Any,
    pair_trades: Counter[str],
    pair_signals: dict[str, dict[str, Any]],
) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "trades" and isinstance(value, list):
                for trade in value:
                    if isinstance(trade, dict) and trade.get("pair"):
                        pair = str(trade["pair"])
                        pair_trades[pair] += 1
                        pair_signals[pair]["enter_long_count"] += 1
                        tag = str(trade.get("enter_tag") or "").strip()
                        if tag:
                            pair_signals[pair]["enter_tags"][tag] += 1
            else:
                parse_backtest_json(value, pair_trades, pair_signals)
    elif isinstance(obj, list):
        for item in obj:
            parse_backtest_json(item, pair_trades, pair_signals)


def parse_pickle_member(name: str, payload: bytes, pair_signals: dict[str, dict[str, Any]]) -> None:
    obj = pickle.loads(payload)
    kind = "enter" if name.endswith("_signals.pkl") else "exit" if name.endswith("_exited.pkl") else "rejected"

    def visit(node: Any, pair_hint: str | None = None) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_text = str(key)
                next_pair = key_text if "/" in key_text else pair_hint
                visit(value, next_pair)
        elif isinstance(node, pd.DataFrame):
            count = int(len(node))
            if not pair_hint or count == 0:
                return
            if kind == "enter":
                pair_signals[pair_hint]["enter_long_count"] += count
                if "enter_tag" in node.columns:
                    for tag, tag_count in node["enter_tag"].dropna().astype(str).value_counts().items():
                        pair_signals[pair_hint]["enter_tags"][tag] += int(tag_count)
            elif kind == "exit":
                pair_signals[pair_hint]["exit_signal_count"] += count

    visit(obj)


def parse_export_files(files: list[Path]) -> tuple[dict[str, dict[str, Any]], Counter[str], list[str]]:
    pair_signals: dict[str, dict[str, Any]] = defaultdict(lambda: {"enter_long_count": 0, "exit_signal_count": 0, "enter_tags": Counter()})
    pair_trades: Counter[str] = Counter()
    parse_notes: list[str] = []
    for path in files:
        if path.suffix != ".zip":
            continue
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.endswith(".pkl"):
                    try:
                        parse_pickle_member(name, zf.read(name), pair_signals)
                    except Exception as exc:
                        parse_notes.append(f"{path.name}:{name}: pkl not parsed ({exc.__class__.__name__})")
                elif name.endswith(".json") and "_config" not in name and "_meta" not in name:
                    try:
                        parse_backtest_json(json.loads(zf.read(name).decode("utf-8")), pair_trades, pair_signals)
                    except Exception as exc:
                        parse_notes.append(f"{path.name}:{name}: json not parsed ({exc.__class__.__name__})")
    return pair_signals, pair_trades, parse_notes


def latest_export_files(group_dir: Path) -> list[Path]:
    zips = sorted(group_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime)
    if not zips:
        return []
    latest_zip = zips[-1]
    stem = latest_zip.stem
    files = [latest_zip]
    files.extend(sorted(group_dir.glob(f"{stem}*")))
    last_result = group_dir / ".last_result.json"
    if last_result.exists():
        files.append(last_result)
    return list(dict.fromkeys(files))


def run_backtest_group(
    name: str,
    pairs: list[str],
    days: int,
    config_path: Path,
    data_rows: list[dict[str, Any]],
    rec: Recorder,
    reuse_exports: bool = False,
) -> dict[str, Any]:
    timerange = timerange_for(days, pairs)
    group_dir = EXPORT_DIR / name
    group_dir.mkdir(parents=True, exist_ok=True)
    rec.section(f"Backtest signals: {name}")
    stdout = ""
    returncode = 0
    if reuse_exports:
        files = latest_export_files(group_dir)
        rec.log(f"[reuse] export files: {', '.join(str(p) for p in files) if files else 'none'}")
        if not files:
            returncode = 1
    else:
        before = {p.resolve() for p in group_dir.rglob("*") if p.is_file()}
        cmd = [
            "freqtrade",
            "backtesting",
            "--config",
            str(config_path),
            "--userdir",
            str(PROJECT_ROOT / "user_data"),
            "--strategy",
            STRATEGY_NAME,
            "--strategy-path",
            str(PROJECT_ROOT / "user_data/strategies"),
            "--pairs",
            *pairs,
            "--timerange",
            timerange,
            "--cache",
            "none",
            "--export",
            "signals",
            "--export-directory",
            str(group_dir),
            "--logfile",
            str(REPORT_DIR / f"{name}.log"),
        ]
        proc = run_cmd(cmd, rec, timeout=7200)
        stdout = proc.stdout or ""
        returncode = proc.returncode
        files = [p for p in group_dir.rglob("*") if p.is_file() and p.resolve() not in before]
    pair_signals, pair_trades, parse_notes = parse_export_files(files)
    total_enter = sum(int(v["enter_long_count"]) for v in pair_signals.values())
    total_exit = sum(int(v["exit_signal_count"]) for v in pair_signals.values())
    total_trades = sum(pair_trades.values()) or parse_total_trades(stdout)
    for row in data_rows:
        if row["group"] == name and row["timeframe"] == "5m":
            stats = pair_signals.get(row["pair"], {})
            row["enter_long_count"] = int(stats.get("enter_long_count", 0))
            row["exit_signal_count"] = int(stats.get("exit_signal_count", 0))
            tags: Counter = stats.get("enter_tags", Counter())
            row["enter_tag_top"] = tags.most_common(1)[0][0] if tags else ""
    if total_enter == 0 and total_trades == 0:
        reason = "raw enter_long signals are zero"
    elif total_enter > 0 and total_trades == 0:
        reason = "signals exist but no trades; inspect config/protections/market constraints"
    else:
        reason = "trades generated; no-trade does not hold for this sample"
    return {
        "group": name,
        "pair_count": len(pairs),
        "timerange": timerange,
        "days": days,
        "returncode": returncode,
        "enter_long_count": int(total_enter),
        "exit_signal_count": int(total_exit),
        "trades_count": int(total_trades),
        "pair_enter_counts": {pair: int(pair_signals.get(pair, {}).get("enter_long_count", 0)) for pair in pairs},
        "pair_trade_counts": {pair: int(pair_trades.get(pair, 0)) for pair in pairs},
        "enter_tag_distribution": {
            pair: dict(pair_signals.get(pair, {}).get("enter_tags", Counter()).most_common(20))
            for pair in pairs
        },
        "export_files": [str(p) for p in files],
        "parse_notes": parse_notes[:20],
        "zero_reason": reason,
    }


def write_backtest_matrix(rows: list[dict[str, Any]]) -> None:
    fields = ["group", "pair_count", "timerange", "days", "returncode", "enter_long_count", "exit_signal_count", "trades_count", "zero_reason"]
    with BACKTEST_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_report(summary: dict[str, Any], data_rows: list[dict[str, Any]], backtests: list[dict[str, Any]]) -> None:
    any_trades = any(row["trades_count"] > 0 for row in backtests)
    any_signal_no_trade = any(row["enter_long_count"] > 0 and row["trades_count"] == 0 for row in backtests)
    lines = [
        "# Expanded Sample Validation Report",
        "",
        f"Generated: `{summary['generated_at']}`",
        "",
        "This report only explains sample-size validation results. It is not a live-trading recommendation and does not prove the strategy profitable or unprofitable.",
        "",
        "## Safety Check",
        f"- Pre safety: `{summary['pre_safety']}`",
        f"- Post safety: `{summary['post_safety']}`",
        f"- Runtime config untouched: `{summary['runtime_config_untouched']}`",
        f"- Sample config: `{summary['sample_config']}`",
        "",
        "## Pairlists",
        f"- Base pairs ({len(summary['base_pairs'])}): `{', '.join(summary['base_pairs'])}`",
        f"- Expanded pairs ({len(summary['expanded_pairs'])}): `{', '.join(summary['expanded_pairs'])}`",
        "",
        "## Backtest / Signal Matrix",
        "| Group | Pair count | Timerange | Enter long | Trades | Interpretation |",
        "|---|---:|---|---:|---:|---|",
    ]
    for row in backtests:
        lines.append(
            f"| `{row['group']}` | {row['pair_count']} | `{row['timerange']}` | {row['enter_long_count']} | {row['trades_count']} | {row['zero_reason']} |"
        )
    lines += [
        "",
        "## Data Quality",
        f"- Data rows checked: `{len(data_rows)}`",
        f"- Missing/issue rows: `{sum(1 for r in data_rows if r.get('notes'))}`",
        "- Full details: `reports/sample_validation/sample_signal_matrix.csv`",
        "",
        "## Conclusion",
    ]
    if any_trades:
        lines.append("- Trades appeared after expanding the sample. The prior 30d/90d no-trade result was mainly caused by a narrow time window and pair universe.")
        lines.append("- Next step: inspect the strategy condition layer and the triggered enter_tag values, especially why the short 90d window did not trigger entries.")
    elif any_signal_no_trade:
        lines.append("- The sample changed from no-signal to signal-but-no-trade. Next step: inspect config filters, protections, stake constraints, and exchange constraints.")
    else:
        lines.append("- All sample groups still have zero enter_long signals. Next step: inspect the strategy condition layer.")
    lines += [
        "",
        "## Output Files",
        "- `reports/sample_validation/sample_validation_report.md`",
        "- `reports/sample_validation/sample_validation_summary.json`",
        "- `reports/sample_validation/sample_signal_matrix.csv`",
        "- `reports/sample_validation/sample_backtest_matrix.csv`",
        "- `reports/sample_validation/sample_validation_logs.txt`",
    ]
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Expanded no-trade sample validation for the local Freqtrade project.")
    parser.add_argument("--skip-download", action="store_true", help="Reuse existing public market data instead of running download-data.")
    parser.add_argument("--reuse-exports", action="store_true", help="Reuse latest Freqtrade export zips instead of running backtesting.")
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    rec = Recorder()
    rec.section("Expanded sample validation")
    rec.log(f"project: {PROJECT_ROOT}")
    rec.log(f"generated_at: {now_utc()}")

    runtime_before = RUNTIME_CONFIG.read_bytes()
    cfg = load_json(RUNTIME_CONFIG)
    pre_safety = assert_runtime_safety(cfg, "before", rec)
    meta = strategy_metadata()
    startup = int(meta.get("startup_candle_count", 800))
    expanded_pairs = generate_expanded_pairs(cfg, rec)
    write_sample_config(cfg, expanded_pairs, rec)
    sample_cfg = load_json(SAMPLE_CONFIG)
    assert_runtime_safety(sample_cfg, "sample config", rec)

    if args.skip_download:
        download_rc: int | str = "skipped"
        rec.section("Download data")
        rec.log("[skip] Reusing existing public market data.")
    else:
        download_rc = download_data(SAMPLE_CONFIG, expanded_pairs, rec)
    if download_rc not in (0, "skipped"):
        rec.log("[WARN] download-data returned non-zero; continuing with available data for diagnostics.")

    groups = [
        ("base_90d", BASE_PAIRS, 90, RUNTIME_CONFIG),
        ("base_180d", BASE_PAIRS, 180, RUNTIME_CONFIG),
        ("base_365d", BASE_PAIRS, 365, RUNTIME_CONFIG),
        ("expanded_180d", expanded_pairs, 180, SAMPLE_CONFIG),
        ("expanded_365d", expanded_pairs, 365, SAMPLE_CONFIG),
    ]
    all_data_rows: list[dict[str, Any]] = []
    for name, pairs, days, _config_path in groups:
        all_data_rows.extend(check_data_quality(pairs, name, timerange_for(days, pairs), startup))
    write_signal_matrix(all_data_rows)

    backtests = []
    for name, pairs, days, config_path in groups:
        if name == "base_90d":
            # Include 90d as requested for validation context, while the comparison focus remains the 4 expanded checks.
            pass
        backtests.append(run_backtest_group(name, pairs, days, config_path, all_data_rows, rec, reuse_exports=args.reuse_exports))
        write_signal_matrix(all_data_rows)
        write_backtest_matrix(backtests)

    post_cfg = load_json(RUNTIME_CONFIG)
    post_safety = assert_runtime_safety(post_cfg, "after", rec)
    runtime_untouched = runtime_before == RUNTIME_CONFIG.read_bytes()
    summary = {
        "generated_at": now_utc(),
        "pre_safety": pre_safety,
        "post_safety": post_safety,
        "runtime_config_untouched": runtime_untouched,
        "sample_config": str(SAMPLE_CONFIG),
        "download_days": DOWNLOAD_DAYS,
        "download_returncode": download_rc,
        "base_pairs": BASE_PAIRS,
        "expanded_pairs": expanded_pairs,
        "timeframes": TIMEFRAMES,
        "groups": backtests,
        "data_quality": {
            "rows_checked": len(all_data_rows),
            "issue_rows": [r for r in all_data_rows if r.get("notes")],
            "missing_rows": [r for r in all_data_rows if not r.get("exists")],
        },
        "no_trade_still_holds": all(row["enter_long_count"] == 0 and row["trades_count"] == 0 for row in backtests),
        "changed_from_no_signal_to_signal_no_trade": any(row["enter_long_count"] > 0 and row["trades_count"] == 0 for row in backtests),
        "recommendation": "sample_range_was_main_factor"
        if any(row["trades_count"] > 0 for row in backtests)
        else "inspect_config_filters"
        if any(row["enter_long_count"] > 0 and row["trades_count"] == 0 for row in backtests)
        else "enter_strategy_condition_explanation",
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    write_report(summary, all_data_rows, backtests)
    rec.section("Outputs")
    for path in (REPORT_MD, SUMMARY_JSON, SIGNAL_CSV, BACKTEST_CSV, LOG_TXT):
        rec.log(str(path))
    rec.write()
    return 0


if __name__ == "__main__":
    sys.exit(main())
