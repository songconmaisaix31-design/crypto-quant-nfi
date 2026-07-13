#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
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
CONFIG_PATH = PROJECT_ROOT / "user_data/config.runtime.json"
REPORT_DIR = PROJECT_ROOT / "reports"
EXPORT_DIR = REPORT_DIR / "no_trade_exports"
REPORT_MD = REPORT_DIR / "no_trade_report.md"
SUMMARY_JSON = REPORT_DIR / "no_trade_summary.json"
SIGNAL_CSV = REPORT_DIR / "signal_matrix.csv"
LOG_TXT = REPORT_DIR / "no_trade_logs.txt"
STRATEGY_NAME = "NostalgiaForInfinityX7"
RISK_TERMS = ("fapi", "dapi", "futures", "margin", "short", "leverage")
LOG_TERMS = (
    "error",
    "exception",
    "warning",
    "ExchangeNotAvailable",
    "502",
    "fapi",
    "dapi",
    "margin",
    "short",
    "leverage",
    "rejected",
    "protection",
    "pairlist",
)
TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440}


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class Recorder:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def log(self, msg: str = "") -> None:
        self.lines.append(msg)
        print(msg)

    def section(self, title: str) -> None:
        self.log(f"\n=== {title} ===")

    def write(self) -> None:
        LOG_TXT.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sanitize_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def run_cmd(cmd: list[str], rec: Recorder, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    rec.log("$ " + sanitize_cmd(cmd))
    proc = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    trimmed = proc.stdout[-12000:] if proc.stdout else ""
    if trimmed:
        rec.log(trimmed.rstrip())
    rec.log(f"[exit] {proc.returncode}")
    return proc


def find_strategy_file() -> Path | None:
    candidates = [
        PROJECT_ROOT / "user_data/strategies/NostalgiaForInfinityX7.py",
        PROJECT_ROOT / "vendor/NostalgiaForInfinity/NostalgiaForInfinityX7.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    matches = sorted(PROJECT_ROOT.glob("**/NostalgiaForInfinityX7.py"))
    return matches[0] if matches else None


def read_strategy_metadata(strategy_file: Path | None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "strategy_file": str(strategy_file) if strategy_file else None,
        "timeframe": None,
        "info_timeframes": [],
        "btc_info_timeframes": [],
        "startup_candle_count": None,
        "can_short_declared": False,
        "sets_can_short_when_futures_or_margin": False,
        "stoploss": None,
        "minimal_roi": None,
        "trailing_stop": None,
        "use_exit_signal": None,
    }
    if not strategy_file or not strategy_file.exists():
        return meta

    text = strategy_file.read_text(encoding="utf-8", errors="ignore")
    patterns = {
        "timeframe": r"^\s*timeframe\s*=\s*['\"]([^'\"]+)['\"]",
        "startup_candle_count": r"^\s*startup_candle_count\s*:?.*=\s*([0-9]+)",
        "stoploss": r"^\s*stoploss\s*=\s*([^\n#]+)",
        "trailing_stop": r"^\s*trailing_stop\s*=\s*([^\n#]+)",
        "use_exit_signal": r"^\s*use_exit_signal\s*=\s*([^\n#]+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.M)
        if match:
            raw = match.group(1).strip()
            if key == "startup_candle_count":
                meta[key] = int(raw)
            else:
                meta[key] = raw.strip()
    for key in ("info_timeframes", "btc_info_timeframes"):
        match = re.search(rf"^\s*{key}\s*=\s*(\[[^\]]*\])", text, re.M)
        if match:
            meta[key] = re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))
    roi_match = re.search(r"^\s*minimal_roi\s*=\s*({.*?})", text, re.M | re.S)
    if roi_match:
        meta["minimal_roi"] = re.sub(r"\s+", " ", roi_match.group(1)).strip()
    meta["can_short_declared"] = bool(re.search(r"^\s*can_short\s*=\s*True", text, re.M))
    meta["sets_can_short_when_futures_or_margin"] = "self.can_short = True" in text and "futures" in text and "margin" in text
    return meta


def config_safety(cfg: dict[str, Any], strategy_meta: dict[str, Any], rec: Recorder) -> dict[str, Any]:
    exchange = cfg.get("exchange", {})
    api = cfg.get("api_server", {})
    checks = {
        "dry_run": cfg.get("dry_run") is True,
        "spot_only": cfg.get("trading_mode") == "spot",
        "margin_empty": cfg.get("margin_mode") in ("", None),
        "api_key_present": bool(exchange.get("key") or exchange.get("secret") or exchange.get("password")),
        "config_can_short_false": cfg.get("can_short") is False,
        "api_localhost": api.get("listen_ip_address") == "127.0.0.1",
        "strategy_can_short_safe_for_spot": not strategy_meta.get("can_short_declared", False) and cfg.get("trading_mode") == "spot",
    }
    searchable = json.dumps(cfg, ensure_ascii=False).lower()
    futures_terms = sorted({term for term in RISK_TERMS if term in searchable})
    risky_enabled = []
    if cfg.get("trading_mode") not in ("spot", None):
        risky_enabled.append(f"trading_mode={cfg.get('trading_mode')}")
    if cfg.get("margin_mode") not in ("", None):
        risky_enabled.append(f"margin_mode={cfg.get('margin_mode')}")
    if cfg.get("can_short") is True:
        risky_enabled.append("can_short=True")
    rec.section("Safety config")
    for key, value in checks.items():
        rec.log(f"{key}: {value}")
    rec.log("risk terms in runtime config text: " + (", ".join(futures_terms) if futures_terms else "none"))
    rec.log("risky enabled settings: " + (", ".join(risky_enabled) if risky_enabled else "none"))
    return {"checks": checks, "futures_terms_found": futures_terms, "risky_enabled": risky_enabled}


def data_path_for(data_dir: Path, pair: str, timeframe: str) -> Path:
    return data_dir / f"{pair.replace('/', '_')}-{timeframe}.feather"


def load_ohlcv(path: Path) -> pd.DataFrame:
    if path.suffix == ".feather":
        return pd.read_feather(path)
    if path.suffix == ".json":
        return pd.read_json(path)
    if path.suffix == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported data file format: {path}")


def check_data(cfg: dict[str, Any], strategy_meta: dict[str, Any], rec: Recorder) -> tuple[list[dict[str, Any]], list[str], list[str], str | None]:
    exchange = cfg.get("exchange", {})
    pairs = list(exchange.get("pair_whitelist") or [])
    base_tf = cfg.get("timeframe") or strategy_meta.get("timeframe") or "5m"
    timeframes = []
    for tf in [base_tf, *strategy_meta.get("info_timeframes", []), *strategy_meta.get("btc_info_timeframes", [])]:
        if tf and tf not in timeframes:
            timeframes.append(tf)
    data_dir = PROJECT_ROOT / "user_data/data" / str(exchange.get("name", "binance"))
    startup = int(strategy_meta.get("startup_candle_count") or 0)
    rows: list[dict[str, Any]] = []
    rec.section("Data quality")
    for pair in pairs:
        for tf in timeframes:
            path = data_path_for(data_dir, pair, tf)
            row: dict[str, Any] = {
                "pair": pair,
                "timeframe": tf,
                "path": str(path),
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
                "candles": 0,
                "start": "",
                "end": "",
                "missing_candles": None,
                "gap_count": None,
                "startup_ok": False,
                "notes": "",
                "enter_long_count": 0,
                "enter_tag_top": "",
                "exit_signal_count": 0,
            }
            notes: list[str] = []
            if not path.exists():
                notes.append("missing data file")
            elif row["size_bytes"] <= 0:
                notes.append("empty data file")
            else:
                try:
                    df = load_ohlcv(path)
                    row["candles"] = int(len(df))
                    if "date" not in df.columns:
                        notes.append("missing date column")
                    elif len(df):
                        df = df.copy()
                        df["date"] = pd.to_datetime(df["date"], utc=True)
                        df = df.sort_values("date")
                        row["start"] = df["date"].iloc[0].isoformat()
                        row["end"] = df["date"].iloc[-1].isoformat()
                        minutes = TF_MINUTES.get(tf)
                        if minutes:
                            expected = pd.Timedelta(minutes=minutes)
                            gaps = df["date"].diff().dropna()
                            missing = gaps[gaps > expected]
                            row["gap_count"] = int(len(missing))
                            row["missing_candles"] = int(((missing / expected) - 1).sum()) if len(missing) else 0
                        base_need = startup if tf == base_tf else max(1, startup * TF_MINUTES.get(base_tf, 5) // max(1, TF_MINUTES.get(tf, 5)))
                        row["startup_ok"] = row["candles"] >= base_need
                        if not row["startup_ok"]:
                            notes.append(f"candles below startup need estimate: {row['candles']} < {base_need}")
                        if row["gap_count"]:
                            notes.append(f"gaps detected: {row['gap_count']}")
                    else:
                        notes.append("empty dataframe")
                except Exception as exc:
                    notes.append(f"read error: {exc!r}")
            row["notes"] = "; ".join(notes)
            rows.append(row)
            rec.log(f"{pair} {tf}: exists={row['exists']} candles={row['candles']} start={row['start']} end={row['end']} notes={row['notes'] or 'ok'}")
    write_signal_csv(rows)
    end_dates = [pd.Timestamp(r["end"]) for r in rows if r["timeframe"] == base_tf and r.get("end")]
    common_end = min(end_dates).strftime("%Y%m%d") if end_dates else None
    return rows, pairs, timeframes, common_end


def write_signal_csv(rows: list[dict[str, Any]]) -> None:
    fields = ["pair", "timeframe", "candles", "start", "end", "enter_long_count", "enter_tag_top", "exit_signal_count", "notes"]
    with SIGNAL_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def timeframe_timeranges(common_end: str | None) -> dict[str, str]:
    if common_end:
        end = dt.datetime.strptime(common_end, "%Y%m%d").date()
    else:
        end = dt.date.today()
    return {
        "30d": f"{(end - dt.timedelta(days=30)).strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}",
        "90d": f"{(end - dt.timedelta(days=90)).strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}",
    }


def run_signal_exports(timeranges: dict[str, str], rec: Recorder) -> dict[str, Any]:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"runs": {}, "signals_supported": True}
    help_proc = run_cmd(["freqtrade", "backtesting", "--help"], rec, timeout=120)
    if "--export {none,trades,signals}" not in help_proc.stdout and "signals" not in help_proc.stdout:
        result["signals_supported"] = False
        rec.log("[WARN] This Freqtrade version did not advertise --export signals.")
        return result

    for label, timerange in timeranges.items():
        run_dir = EXPORT_DIR / label
        run_dir.mkdir(parents=True, exist_ok=True)
        before = {p.resolve() for p in run_dir.rglob("*") if p.is_file()}
        cmd = [
            "freqtrade",
            "backtesting",
            "--config",
            str(CONFIG_PATH),
            "--userdir",
            str(PROJECT_ROOT / "user_data"),
            "--strategy",
            STRATEGY_NAME,
            "--strategy-path",
            str(PROJECT_ROOT / "user_data/strategies"),
            "--timerange",
            timerange,
            "--cache",
            "none",
            "--export",
            "signals",
            "--export-directory",
            str(run_dir),
            "--logfile",
            str(REPORT_DIR / f"no_trade_backtest_{label}.log"),
        ]
        proc = run_cmd(cmd, rec, timeout=2400)
        after = [p for p in run_dir.rglob("*") if p.is_file() and p.resolve() not in before]
        result["runs"][label] = {
            "timerange": timerange,
            "returncode": proc.returncode,
            "files": [str(p) for p in after],
            "stdout_tail": proc.stdout[-6000:] if proc.stdout else "",
        }
    return result


def iter_export_records(path: Path, rec: Recorder):
    try:
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    if name.endswith(".json"):
                        data = json.loads(zf.read(name).decode("utf-8"))
                        yield from walk_records(data)
                    elif name.endswith(".feather"):
                        with zf.open(name) as raw:
                            df = pd.read_feather(io.BytesIO(raw.read()))
                        yield from df.to_dict("records")
        elif path.suffix == ".json":
            yield from walk_records(json.loads(path.read_text(encoding="utf-8")))
        elif path.suffix == ".feather":
            yield from pd.read_feather(path).to_dict("records")
        elif path.suffix == ".csv":
            yield from pd.read_csv(path).to_dict("records")
        elif path.suffix == ".pkl":
            obj = pickle.loads(path.read_bytes())
            yield from walk_records(obj)
    except Exception as exc:
        rec.log(f"[WARN] Could not parse export {path}: {exc!r}")


def parse_pickle_member(path: Path, member_name: str, payload: bytes, pair_stats: dict[str, dict[str, Any]], rec: Recorder) -> None:
    try:
        obj = pickle.loads(payload)
    except Exception as exc:
        rec.log(f"[WARN] Could not parse pickle member {path}:{member_name}: {exc!r}")
        return
    signal_kind = "enter" if "_signals.pkl" in member_name else "exit" if "_exited.pkl" in member_name else "rejected"

    def visit(node: Any, pair_hint: str | None = None) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_text = str(key)
                next_pair = key_text if "/" in key_text else pair_hint
                visit(value, next_pair)
            return
        if isinstance(node, pd.DataFrame):
            count = int(len(node))
            if pair_hint and count:
                if signal_kind == "enter":
                    pair_stats[pair_hint]["enter_long_count"] += count
                    if "enter_tag" in node.columns:
                        for tag, tag_count in node["enter_tag"].dropna().astype(str).value_counts().items():
                            pair_stats[pair_hint]["enter_tags"][tag] += int(tag_count)
                elif signal_kind == "exit":
                    pair_stats[pair_hint]["exit_signal_count"] += count

    visit(obj)


def walk_records(obj: Any):
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            for item in obj:
                yield item
        else:
            for item in obj:
                yield from walk_records(item)
    elif isinstance(obj, dict):
        if any(k in obj for k in ("pair", "enter_long", "enter_tag", "exit_long", "exit_tag", "trades")):
            yield obj
        for value in obj.values():
            yield from walk_records(value)


def truthy_signal(value: Any) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "long", "enter_long")
    return False


def parse_signal_exports(signal_result: dict[str, Any], rows: list[dict[str, Any]], rec: Recorder) -> dict[str, Any]:
    pair_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"enter_long_count": 0, "exit_signal_count": 0, "enter_tags": Counter()})
    trades_count = 0
    files_seen = []
    for run in signal_result.get("runs", {}).values():
        for raw in run.get("files", []):
            path = Path(raw)
            files_seen.append(str(path))
            if path.suffix == ".zip":
                try:
                    with zipfile.ZipFile(path) as zf:
                        for member_name in zf.namelist():
                            if member_name.endswith(".pkl"):
                                parse_pickle_member(path, member_name, zf.read(member_name), pair_stats, rec)
                except Exception as exc:
                    rec.log(f"[WARN] Could not scan pickle members in {path}: {exc!r}")
            for rec_item in iter_export_records(path, rec):
                if not isinstance(rec_item, dict):
                    continue
                if "trades" in rec_item and isinstance(rec_item["trades"], list):
                    trades_count += len(rec_item["trades"])
                pair = str(rec_item.get("pair") or rec_item.get("Pair") or "")
                if not pair:
                    continue
                if truthy_signal(rec_item.get("enter_long")) or truthy_signal(rec_item.get("buy")):
                    pair_stats[pair]["enter_long_count"] += 1
                    tag = str(rec_item.get("enter_tag") or rec_item.get("buy_tag") or "").strip()
                    if tag:
                        pair_stats[pair]["enter_tags"][tag] += 1
                if truthy_signal(rec_item.get("exit_long")) or truthy_signal(rec_item.get("sell")) or truthy_signal(rec_item.get("exit_signal")):
                    pair_stats[pair]["exit_signal_count"] += 1
    total_enter = sum(v["enter_long_count"] for v in pair_stats.values())
    total_exit = sum(v["exit_signal_count"] for v in pair_stats.values())
    for row in rows:
        if row.get("timeframe") != "5m":
            continue
        stats = pair_stats.get(row["pair"], {})
        row["enter_long_count"] = int(stats.get("enter_long_count", 0))
        row["exit_signal_count"] = int(stats.get("exit_signal_count", 0))
        tags: Counter = stats.get("enter_tags", Counter())
        row["enter_tag_top"] = tags.most_common(1)[0][0] if tags else ""
    write_signal_csv(rows)
    rec.section("Signal export parse")
    rec.log(f"export files parsed: {len(files_seen)}")
    rec.log(f"enter_long_count: {total_enter}")
    rec.log(f"exit_signal_count: {total_exit}")
    rec.log(f"trades_count parsed: {trades_count}")
    return {
        "files_seen": files_seen,
        "pair_stats": {
            pair: {
                "enter_long_count": stats["enter_long_count"],
                "exit_signal_count": stats["exit_signal_count"],
                "enter_tags": dict(stats["enter_tags"].most_common(20)),
            }
            for pair, stats in pair_stats.items()
        },
        "enter_long_count": total_enter,
        "exit_signal_count": total_exit,
        "trades_count": trades_count,
    }


def extract_trades_count(signal_result: dict[str, Any]) -> int:
    total = 0
    for run in signal_result.get("runs", {}).values():
        text = run.get("stdout_tail", "")
        matches = re.findall(r"TOTAL\s+\|\s+([0-9]+)\s+\|", text)
        if matches:
            total += int(matches[-1])
    return total


def inspect_logs(rec: Recorder) -> list[str]:
    logs = []
    candidates = [
        PROJECT_ROOT / "user_data/logs/freqtrade.log",
        PROJECT_ROOT / "user_data/logs/freqtrade-native.log",
        PROJECT_ROOT / "user_data/logs/freqtrade-native.wslproc.out.log",
        PROJECT_ROOT / "user_data/logs/freqtrade-native.wslproc.err.log",
    ]
    network_log_dir = PROJECT_ROOT / "user_data/logs/network-repair"
    if network_log_dir.exists():
        candidates.extend(sorted(network_log_dir.glob("*.log")))
    seen = set()
    for path in candidates:
        if not path.exists() or path in seen:
            continue
        seen.add(path)
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-600:]
        except Exception as exc:
            logs.append(f"{path}: read error {exc!r}")
            continue
        for line in lines:
            lower = line.lower()
            if any(term.lower() in lower for term in LOG_TERMS):
                logs.append(f"{path.name}: {line[-500:]}")
    rec.section("Log scan")
    for line in logs[-120:]:
        rec.log(line)
    if not logs:
        rec.log("No matching warning/error terms found in recent logs.")
    return logs[-120:]


def config_filter_notes(cfg: dict[str, Any], strategy_meta: dict[str, Any]) -> list[str]:
    notes = []
    exchange = cfg.get("exchange", {})
    pairlists = cfg.get("pairlists") or []
    protections = cfg.get("protections") or []
    if cfg.get("max_open_trades", 0) == 0:
        notes.append("max_open_trades is 0, which would block entries.")
    else:
        notes.append(f"max_open_trades={cfg.get('max_open_trades')} does not by itself explain zero trades.")
    stake = cfg.get("stake_amount")
    if stake in (0, "0"):
        notes.append("stake_amount is zero.")
    else:
        notes.append(f"stake_amount={stake}.")
    notes.append(f"tradable_balance_ratio={cfg.get('tradable_balance_ratio')}.")
    notes.append(f"pairlist={pairlists}; whitelist has {len(exchange.get('pair_whitelist') or [])} pairs.")
    notes.append(f"protections={protections or 'none configured'}.")
    notes.append(f"startup_candle_count={strategy_meta.get('startup_candle_count')} with base timeframe {cfg.get('timeframe') or strategy_meta.get('timeframe')}.")
    notes.append(f"stoploss={strategy_meta.get('stoploss')}; trailing_stop={strategy_meta.get('trailing_stop')}; use_exit_signal={strategy_meta.get('use_exit_signal')}.")
    if exchange.get("pair_blacklist"):
        notes.append("pair_blacklist is present, but current whitelist pairs are not leveraged-token names.")
    return notes


def determine_likely_causes(
    data_rows: list[dict[str, Any]],
    signal_stats: dict[str, Any],
    cfg: dict[str, Any],
    pairs: list[str],
    timeranges: dict[str, str],
) -> tuple[list[str], list[str]]:
    causes: list[str] = []
    recommendations: list[str] = []
    bad_data = [r for r in data_rows if r.get("notes")]
    enter_count = int(signal_stats.get("enter_long_count") or 0)
    trades_count = int(signal_stats.get("trades_count") or 0)
    if bad_data:
        causes.append("部分数据文件存在缺失、gap 或 startup candle 不足，需要先看 signal_matrix.csv 的 notes。")
        recommendations.append("先修复 signal_matrix.csv 中标记的数据问题，再重新运行诊断。")
    if enter_count == 0:
        causes.append("策略原始 enter_long 信号为 0，这是当前 0 交易最直接原因。")
        recommendations.append("优先检查策略入场条件与当前市场样本是否过窄，而不是调整资金或保护参数。")
    elif trades_count == 0:
        causes.append("存在 enter_long 信号但最终 trades 为 0，更可能是配置过滤、资金、pairlist 或保护层限制。")
        recommendations.append("重点检查 max_open_trades、stake_amount、pairlist、protections 和最小下单金额。")
    if len(pairs) <= 5:
        causes.append("交易对范围很窄，仅 5 个主流 USDT pair，NFI 条件严格时 30d/90d 可能没有触发。")
        recommendations.append("只做后续实验时，可考虑扩展到 20-50 个 USDT spot 交易对；不要自动启用真实交易。")
    causes.append(f"当前样本窗口为 {timeranges.get('30d')} 和 {timeranges.get('90d')}；对严格策略可能偏短。")
    recommendations.append("后续可增加 180d/365d 回测窗口来判断是否只是时间范围过短。")
    recommendations.append("保持 dry_run=True、spot、can_short=False、本机 FreqUI，再做任何扩展实验。")
    return causes, recommendations


def write_report(
    cfg: dict[str, Any],
    strategy_meta: dict[str, Any],
    safety: dict[str, Any],
    data_rows: list[dict[str, Any]],
    pairs: list[str],
    timeframes: list[str],
    timeranges: dict[str, str],
    signal_result: dict[str, Any],
    signal_stats: dict[str, Any],
    config_notes: list[str],
    log_lines: list[str],
    causes: list[str],
    recommendations: list[str],
) -> None:
    exchange = cfg.get("exchange", {})
    positive_safety = (
        safety["checks"].get("dry_run")
        and safety["checks"].get("spot_only")
        and safety["checks"].get("margin_empty")
        and not safety["checks"].get("api_key_present")
        and safety["checks"].get("config_can_short_false")
        and safety["checks"].get("api_localhost")
        and not safety["risky_enabled"]
    )
    summary = {
        "generated_at": now_utc(),
        "safe_config": bool(positive_safety),
        "dry_run": cfg.get("dry_run") is True,
        "spot_only": cfg.get("trading_mode") == "spot" and cfg.get("margin_mode") in ("", None),
        "api_key_present": bool(exchange.get("key") or exchange.get("secret") or exchange.get("password")),
        "futures_terms_found": safety["futures_terms_found"],
        "risky_enabled": safety["risky_enabled"],
        "pairs_checked": pairs,
        "timeframes_checked": timeframes,
        "timeranges_checked": timeranges,
        "data_files_count": sum(1 for r in data_rows if r.get("exists")),
        "enter_long_count": int(signal_stats.get("enter_long_count") or 0),
        "exit_signal_count": int(signal_stats.get("exit_signal_count") or 0),
        "trades_count": int(signal_stats.get("trades_count") or 0),
        "signals_supported": signal_result.get("signals_supported", False),
        "likely_causes": causes,
        "recommended_next_steps": recommendations,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# No-trade Diagnostic Report",
        "",
        f"Generated: `{summary['generated_at']}`",
        "",
        "本报告不代表策略有效或无效，只解释当前配置下为什么没有交易。",
        "",
        "## 诊断结论",
    ]
    for idx, cause in enumerate(causes, 1):
        lines.append(f"{idx}. {cause}")
    lines += [
        "",
        "## 当前配置快照",
        f"- Strategy: `{STRATEGY_NAME}`",
        f"- Strategy file: `{strategy_meta.get('strategy_file')}`",
        f"- Exchange: `{exchange.get('name')}`",
        f"- Pairs: `{', '.join(pairs)}`",
        f"- Timeframes: `{', '.join(timeframes)}`",
        f"- Timeranges checked: `{timeranges}`",
        f"- Stake: `{cfg.get('stake_amount')} {cfg.get('stake_currency')}`",
        f"- max_open_trades: `{cfg.get('max_open_trades')}`",
        "",
        "## 安全边界检查",
        f"- dry_run=True: `{summary['dry_run']}`",
        f"- spot_only: `{summary['spot_only']}`",
        f"- API key present: `{summary['api_key_present']}`",
        f"- can_short config false: `{safety['checks'].get('config_can_short_false')}`",
        f"- FreqUI localhost: `{safety['checks'].get('api_localhost')}`",
        f"- Risk terms found in config text: `{summary['futures_terms_found']}`",
        f"- Risky enabled settings: `{summary['risky_enabled']}`",
        "",
        "## 数据层检查结果",
        f"- Existing data files: `{summary['data_files_count']}`",
        f"- CSV: `reports/signal_matrix.csv`",
    ]
    data_notes = [r for r in data_rows if r.get("notes")]
    if data_notes:
        lines.append("- Data issues:")
        for row in data_notes[:20]:
            lines.append(f"  - `{row['pair']} {row['timeframe']}`: {row['notes']}")
    else:
        lines.append("- Data quality: no missing file/gap/startup issue detected by this diagnostic.")

    lines += [
        "",
        "## 策略信号检查结果",
        f"- Signals export supported: `{signal_result.get('signals_supported')}`",
        f"- enter_long_count: `{summary['enter_long_count']}`",
        f"- exit_signal_count: `{summary['exit_signal_count']}`",
        f"- trades_count: `{summary['trades_count']}`",
    ]
    if summary["enter_long_count"] == 0:
        lines.append("- 结论：策略原始入场信号为 0。")
    elif summary["trades_count"] == 0:
        lines.append("- 结论：有入场信号但无成交，需要继续看配置/保护/资金过滤。")

    lines += [
        "",
        "## 配置层检查结果",
    ]
    lines.extend(f"- {note}" for note in config_notes)
    lines += [
        "",
        "## 样本范围检查",
        f"- Pair count: `{len(pairs)}`",
        "- 当前交易对集中在 BTC/ETH/SOL/XRP/ADA 等主流 USDT spot，样本偏窄。",
        "- 建议后续只在 dry-run/backtest 场景下扩展到 180d/365d 和 20-50 个 USDT spot 交易对。",
        "",
        "## 日志摘要",
    ]
    if log_lines:
        lines.extend(f"- `{line}`" for line in log_lines[-40:])
    else:
        lines.append("- 未发现匹配关键词的近期日志。")
    lines += [
        "",
        "## 下一步建议",
    ]
    lines.extend(f"- {step}" for step in recommendations)
    lines += [
        "",
        "## 输出文件",
        "- `reports/no_trade_report.md`",
        "- `reports/no_trade_summary.json`",
        "- `reports/signal_matrix.csv`",
        "- `reports/no_trade_logs.txt`",
    ]
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose why current NFI/Freqtrade backtests produced no trades.")
    parser.add_argument("--skip-backtest", action="store_true", help="Skip Freqtrade --export signals runs and only inspect existing files.")
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rec = Recorder()
    rec.section("No-trade diagnostic")
    rec.log(f"project: {PROJECT_ROOT}")
    rec.log(f"generated_at: {now_utc()}")

    if not CONFIG_PATH.exists():
        rec.log(f"[FAIL] Missing runtime config: {CONFIG_PATH}")
        rec.write()
        return 2
    cfg = load_json(CONFIG_PATH)
    strategy_file = find_strategy_file()
    strategy_meta = read_strategy_metadata(strategy_file)
    safety = config_safety(cfg, strategy_meta, rec)
    data_rows, pairs, timeframes, common_end = check_data(cfg, strategy_meta, rec)
    timeranges = timeframe_timeranges(common_end)

    if args.skip_backtest:
        signal_result = {"runs": {}, "signals_supported": False, "skipped": True}
        signal_stats = {"enter_long_count": 0, "exit_signal_count": 0, "trades_count": 0, "pair_stats": {}}
    else:
        rec.section("Freqtrade signal export")
        signal_result = run_signal_exports(timeranges, rec)
        signal_stats = parse_signal_exports(signal_result, data_rows, rec)
        parsed_trades = extract_trades_count(signal_result)
        if parsed_trades:
            signal_stats["trades_count"] = parsed_trades

    config_notes = config_filter_notes(cfg, strategy_meta)
    rec.section("Config filters")
    for note in config_notes:
        rec.log(note)
    log_lines = inspect_logs(rec)
    causes, recommendations = determine_likely_causes(data_rows, signal_stats, cfg, pairs, timeranges)
    write_report(
        cfg,
        strategy_meta,
        safety,
        data_rows,
        pairs,
        timeframes,
        timeranges,
        signal_result,
        signal_stats,
        config_notes,
        log_lines,
        causes,
        recommendations,
    )
    rec.section("Outputs")
    for path in (REPORT_MD, SUMMARY_JSON, SIGNAL_CSV, LOG_TXT):
        rec.log(str(path))
    rec.write()
    return 0


if __name__ == "__main__":
    sys.exit(main())
