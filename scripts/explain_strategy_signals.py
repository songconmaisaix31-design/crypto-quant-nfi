#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import re
import statistics
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
STRATEGY_PATHS = [
    PROJECT_ROOT / "user_data/strategies/NostalgiaForInfinityX7.py",
    PROJECT_ROOT / "vendor/NostalgiaForInfinity/NostalgiaForInfinityX7.py",
]
REPORT_DIR = PROJECT_ROOT / "reports/strategy_explain"
SAMPLE_DIR = PROJECT_ROOT / "reports/sample_validation"
NO_TRADE_DIR = PROJECT_ROOT / "reports"
ENTER_TAG_CSV = REPORT_DIR / "enter_tag_summary.csv"
PAIR_CSV = REPORT_DIR / "pair_signal_summary.csv"
TRADE_CONTEXT_CSV = REPORT_DIR / "trade_context.csv"
NO_SIGNAL_MD = REPORT_DIR / "no_signal_90d_analysis.md"
CONDITIONS_MD = REPORT_DIR / "strategy_conditions.md"
REPORT_MD = REPORT_DIR / "strategy_explain_report.md"
SUMMARY_JSON = REPORT_DIR / "strategy_explain_summary.json"
LOG_TXT = REPORT_DIR / "strategy_explain_logs.txt"
STRATEGY_NAME = "NostalgiaForInfinityX7"
BASE_PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT"]
RISK_WORDS = ("fapi", "dapi", "futures", "margin", "short", "leverage")

TAG_GROUPS = {
    "normal": set(str(i) for i in range(1, 14)),
    "pump": set(str(i) for i in range(21, 27)),
    "quick": set(str(i) for i in range(41, 54)),
    "rebuy": {"61", "62", "63", "65"},
    "high_profit": {"81", "82"},
    "rapid": set(str(i) for i in range(101, 111)),
    "grind": {"120"},
    "btc": {"121"},
    "top_coins": {"141", "142", "143", "144", "145"},
    "scalp": {"161", "162", "163"},
}


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


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_safety(label: str, rec: Recorder) -> dict[str, Any]:
    cfg = load_json(RUNTIME_CONFIG)
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
        raise RuntimeError(f"Unsafe runtime config: {checks}, enabled_risks={enabled_risks}")
    return {"checks": checks, "enabled_risks": enabled_risks}


def strategy_path() -> Path:
    for path in STRATEGY_PATHS:
        if path.exists():
            return path
    raise FileNotFoundError("NostalgiaForInfinityX7.py not found")


def latest_zip(directory: Path) -> Path | None:
    zips = sorted(directory.glob("*.zip"), key=lambda p: p.stat().st_mtime)
    return zips[-1] if zips else None


def discover_export_zips() -> dict[str, Path]:
    groups: dict[str, Path] = {}
    for parent in (SAMPLE_DIR / "exports").glob("*"):
        if parent.is_dir():
            z = latest_zip(parent)
            if z:
                groups[parent.name] = z
    for parent in (NO_TRADE_DIR / "no_trade_exports").glob("*"):
        if parent.is_dir():
            z = latest_zip(parent)
            if z:
                groups[f"no_trade_{parent.name}"] = z
    return groups


def extract_strategy_payload(obj: dict[str, Any]) -> dict[str, Any]:
    strategy = obj.get("strategy")
    if isinstance(strategy, dict):
        if STRATEGY_NAME in strategy:
            return strategy[STRATEGY_NAME]
        if len(strategy) == 1:
            only = next(iter(strategy.values()))
            if isinstance(only, dict):
                return only
    return obj


def read_export(zip_path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {"zip": str(zip_path), "trades": [], "raw": {}}
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith(".json") and "_config" not in name and "_meta" not in name:
                obj = json.loads(zf.read(name).decode("utf-8"))
                data = extract_strategy_payload(obj)
                payload["raw"] = data
                trades = data.get("trades", [])
                if isinstance(trades, list):
                    payload["trades"] = trades
                break
    return payload


def parse_exports(rec: Recorder) -> dict[str, dict[str, Any]]:
    rec.section("Read existing exports")
    exports = {}
    for group, zip_path in sorted(discover_export_zips().items()):
        data = read_export(zip_path)
        exports[group] = data
        rec.log(f"{group}: {len(data['trades'])} trades from {zip_path}")
    return exports


def preferred_primary_group(exports: dict[str, dict[str, Any]]) -> str:
    for name in ("expanded_365d", "expanded_180d", "base_365d", "base_180d"):
        if name in exports:
            return name
    if not exports:
        return ""
    return max(exports, key=lambda k: len(exports[k].get("trades", [])))


def parse_date(value: Any) -> pd.Timestamp | None:
    if not value:
        return None
    try:
        return pd.to_datetime(value, utc=True)
    except Exception:
        return None


def tag_key(trade: dict[str, Any]) -> str:
    return str(trade.get("enter_tag") or "").strip() or "unknown"


def profit_ratio(trade: dict[str, Any]) -> float:
    try:
        return float(trade.get("profit_ratio") or 0.0)
    except Exception:
        return 0.0


def profit_abs(trade: dict[str, Any]) -> float:
    try:
        return float(trade.get("profit_abs") or 0.0)
    except Exception:
        return 0.0


def trade_duration(trade: dict[str, Any]) -> float:
    try:
        return float(trade.get("trade_duration") or 0.0)
    except Exception:
        return 0.0


def pct(value: float) -> float:
    return round(value * 100.0, 6)


def safe_mean(values: list[float]) -> float:
    return round(statistics.mean(values), 8) if values else 0.0


def write_enter_tag_summary(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        by_tag[tag_key(trade)].append(trade)
    rows = []
    for tag, items in sorted(by_tag.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        profits = [profit_ratio(t) for t in items]
        durations = [trade_duration(t) for t in items]
        pairs = {str(t.get("pair")) for t in items if t.get("pair")}
        rows.append(
            {
                "enter_tag": tag,
                "tag_groups": classify_tag(tag),
                "occurrences": len(items),
                "pair_count": len(pairs),
                "pairs": " ".join(sorted(pairs)),
                "trades_count": len(items),
                "avg_profit_pct": pct(safe_mean(profits)),
                "win_rate_pct": pct(sum(1 for p in profits if p > 0) / len(profits)) if profits else 0.0,
                "avg_duration_min": round(safe_mean(durations), 3),
                "max_loss_pct": pct(min(profits)) if profits else 0.0,
                "max_profit_pct": pct(max(profits)) if profits else 0.0,
            }
        )
    write_csv(
        ENTER_TAG_CSV,
        [
            "enter_tag",
            "tag_groups",
            "occurrences",
            "pair_count",
            "pairs",
            "trades_count",
            "avg_profit_pct",
            "win_rate_pct",
            "avg_duration_min",
            "max_loss_pct",
            "max_profit_pct",
        ],
        rows,
    )
    return rows


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def group_pair_counts(exports: dict[str, dict[str, Any]]) -> dict[str, Counter[str]]:
    out: dict[str, Counter[str]] = {}
    for group, data in exports.items():
        c: Counter[str] = Counter()
        for trade in data.get("trades", []):
            if trade.get("pair"):
                c[str(trade["pair"])] += 1
        out[group] = c
    return out


def write_pair_summary(trades: list[dict[str, Any]], exports: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        if trade.get("pair"):
            by_pair[str(trade["pair"])].append(trade)
    group_counts = group_pair_counts(exports)
    all_pairs = sorted(set(by_pair) | set(BASE_PAIRS))
    rows = []
    for pair in all_pairs:
        items = by_pair.get(pair, [])
        profits = [profit_ratio(t) for t in items]
        tags = Counter(tag_key(t) for t in items)
        rows.append(
            {
                "pair": pair,
                "enter_long_count": len(items),
                "trades_count": len(items),
                "win_rate_pct": pct(sum(1 for p in profits if p > 0) / len(profits)) if profits else 0.0,
                "total_profit_abs": round(sum(profit_abs(t) for t in items), 8),
                "total_profit_pct_sum": pct(sum(profits)),
                "max_loss_trade_pct": pct(min(profits)) if profits else 0.0,
                "most_common_enter_tag": tags.most_common(1)[0][0] if tags else "",
                "base_90d_trades": group_counts.get("base_90d", Counter()).get(pair, 0),
                "base_180d_trades": group_counts.get("base_180d", Counter()).get(pair, 0),
                "base_365d_trades": group_counts.get("base_365d", Counter()).get(pair, 0),
                "expanded_180d_trades": group_counts.get("expanded_180d", Counter()).get(pair, 0),
                "expanded_365d_trades": group_counts.get("expanded_365d", Counter()).get(pair, 0),
                "no_signal_90d_but_later_signal": bool(
                    group_counts.get("base_90d", Counter()).get(pair, 0) == 0
                    and (
                        group_counts.get("base_180d", Counter()).get(pair, 0) > 0
                        or group_counts.get("base_365d", Counter()).get(pair, 0) > 0
                        or group_counts.get("expanded_180d", Counter()).get(pair, 0) > 0
                        or group_counts.get("expanded_365d", Counter()).get(pair, 0) > 0
                    )
                ),
            }
        )
    write_csv(
        PAIR_CSV,
        [
            "pair",
            "enter_long_count",
            "trades_count",
            "win_rate_pct",
            "total_profit_abs",
            "total_profit_pct_sum",
            "max_loss_trade_pct",
            "most_common_enter_tag",
            "base_90d_trades",
            "base_180d_trades",
            "base_365d_trades",
            "expanded_180d_trades",
            "expanded_365d_trades",
            "no_signal_90d_but_later_signal",
        ],
        rows,
    )
    return rows


def data_file(pair: str, timeframe: str = "5m") -> Path:
    return PROJECT_ROOT / "user_data/data/binance" / f"{pair.replace('/', '_')}-{timeframe}.feather"


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, math.nan)
    return 100 - (100 / (1 + rs))


def pct_change_between(series: pd.Series, idx: int, lookback: int) -> float | None:
    before = idx - lookback
    if before < 0 or idx >= len(series):
        return None
    start = float(series.iloc[before])
    end = float(series.iloc[idx])
    if start == 0:
        return None
    return pct((end / start) - 1)


def volume_change(df: pd.DataFrame, idx: int, lookback: int) -> float | None:
    before_start = idx - (lookback * 2)
    mid = idx - lookback
    if before_start < 0 or mid < 0:
        return None
    prev = float(df["volume"].iloc[before_start:mid].mean())
    recent = float(df["volume"].iloc[mid:idx].mean())
    if prev == 0 or math.isnan(prev) or math.isnan(recent):
        return None
    return pct((recent / prev) - 1)


def market_regime(row: dict[str, Any]) -> str:
    r12 = row.get("pre_12_return_pct")
    r48 = row.get("pre_48_return_pct")
    r288 = row.get("pre_288_return_pct")
    close_vs_ema50 = row.get("close_vs_ema50_pct")
    if isinstance(r48, (int, float)) and isinstance(r12, (int, float)) and r48 <= -8 and r12 >= 1:
        return "fast_drop_rebound"
    if isinstance(r288, (int, float)) and isinstance(close_vs_ema50, (int, float)) and r288 >= 10 and close_vs_ema50 >= 0:
        return "trend_up"
    if isinstance(r288, (int, float)) and isinstance(close_vs_ema50, (int, float)) and r288 <= -10 and close_vs_ema50 <= 0:
        return "trend_down"
    if isinstance(r48, (int, float)) and abs(r48) <= 3:
        return "rangebound_or_compression"
    return "mixed"


def write_trade_context(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cache: dict[str, pd.DataFrame] = {}
    rows = []
    for trade in trades:
        pair = str(trade.get("pair") or "")
        path = data_file(pair, "5m")
        note = ""
        df = cache.get(pair)
        if df is None:
            if not path.exists():
                note = "missing 5m OHLCV file"
                df = pd.DataFrame()
            else:
                try:
                    df = pd.read_feather(path)
                    df["date"] = pd.to_datetime(df["date"], utc=True)
                    df = df.sort_values("date").reset_index(drop=True)
                    df["rsi_14_recomputed"] = rsi(df["close"], 14)
                    df["ema_20_recomputed"] = df["close"].ewm(span=20, adjust=False).mean()
                    df["ema_50_recomputed"] = df["close"].ewm(span=50, adjust=False).mean()
                    df["ema_200_recomputed"] = df["close"].ewm(span=200, adjust=False).mean()
                except Exception as exc:
                    note = f"read/indicator error: {exc!r}"
                    df = pd.DataFrame()
            cache[pair] = df
        open_ts = parse_date(trade.get("open_date"))
        row: dict[str, Any] = {
            "pair": pair,
            "open_date": trade.get("open_date", ""),
            "close_date": trade.get("close_date", ""),
            "enter_tag": tag_key(trade),
            "tag_groups": classify_tag(tag_key(trade)),
            "profit_ratio": round(profit_ratio(trade), 8),
            "profit_pct": pct(profit_ratio(trade)),
            "trade_duration_min": trade_duration(trade),
            "open_rate": trade.get("open_rate", ""),
            "close_rate": trade.get("close_rate", ""),
            "timeframe": "5m",
            "pre_12_return_pct": "",
            "pre_48_return_pct": "",
            "pre_288_return_pct": "",
            "volume_change_48_pct": "",
            "rsi_14_recomputed": "",
            "ema_20": "",
            "ema_50": "",
            "ema_200": "",
            "close_vs_ema50_pct": "",
            "close_vs_ema200_pct": "",
            "market_regime": "unknown",
            "notes": note,
        }
        if open_ts is not None and not df.empty:
            matches = df.index[df["date"] <= open_ts]
            if len(matches):
                idx = int(matches[-1])
                close = float(df["close"].iloc[idx])
                for lookback, key in ((12, "pre_12_return_pct"), (48, "pre_48_return_pct"), (288, "pre_288_return_pct")):
                    val = pct_change_between(df["close"], idx, lookback)
                    row[key] = "" if val is None else val
                vol = volume_change(df, idx, 48)
                row["volume_change_48_pct"] = "" if vol is None else vol
                for col, key in (
                    ("rsi_14_recomputed", "rsi_14_recomputed"),
                    ("ema_20_recomputed", "ema_20"),
                    ("ema_50_recomputed", "ema_50"),
                    ("ema_200_recomputed", "ema_200"),
                ):
                    val = df[col].iloc[idx]
                    row[key] = "" if pd.isna(val) else round(float(val), 8)
                if row["ema_50"]:
                    row["close_vs_ema50_pct"] = pct((close / float(row["ema_50"])) - 1)
                if row["ema_200"]:
                    row["close_vs_ema200_pct"] = pct((close / float(row["ema_200"])) - 1)
                row["market_regime"] = market_regime(row)
            else:
                row["notes"] = (row["notes"] + "; " if row["notes"] else "") + "open_date before data start"
        rows.append(row)
    write_csv(
        TRADE_CONTEXT_CSV,
        [
            "pair",
            "open_date",
            "close_date",
            "enter_tag",
            "tag_groups",
            "profit_ratio",
            "profit_pct",
            "trade_duration_min",
            "open_rate",
            "close_rate",
            "timeframe",
            "pre_12_return_pct",
            "pre_48_return_pct",
            "pre_288_return_pct",
            "volume_change_48_pct",
            "rsi_14_recomputed",
            "ema_20",
            "ema_50",
            "ema_200",
            "close_vs_ema50_pct",
            "close_vs_ema200_pct",
            "market_regime",
            "notes",
        ],
        rows,
    )
    return rows


def classify_tag(tag: str) -> str:
    groups = []
    for token in str(tag).split():
        found = [name for name, values in TAG_GROUPS.items() if token in values]
        groups.append(f"{token}:{'/'.join(found) if found else 'unknown'}")
    return " ".join(groups) if groups else "unknown"


def sample_summary() -> dict[str, Any]:
    path = SAMPLE_DIR / "sample_validation_summary.json"
    return load_json(path) if path.exists() else {}


def no_trade_summary() -> dict[str, Any]:
    path = NO_TRADE_DIR / "no_trade_summary.json"
    return load_json(path) if path.exists() else {}


def group_timerange(summary: dict[str, Any], group: str) -> str:
    for item in summary.get("groups", []):
        if item.get("group") == group:
            return str(item.get("timerange", ""))
    return ""


def timerange_start(timerange: str) -> pd.Timestamp | None:
    if not timerange or "-" not in timerange:
        return None
    start = timerange.split("-", 1)[0]
    try:
        return pd.to_datetime(start, format="%Y%m%d", utc=True)
    except Exception:
        return None


def write_no_signal_analysis(exports: dict[str, dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    base90 = exports.get("base_90d", {}).get("trades", [])
    base180 = exports.get("base_180d", {}).get("trades", [])
    base365 = exports.get("base_365d", {}).get("trades", [])
    expanded180 = exports.get("expanded_180d", {}).get("trades", [])
    expanded365 = exports.get("expanded_365d", {}).get("trades", [])
    start90 = timerange_start(group_timerange(summary, "base_90d"))
    base_later = [t for t in base180 + base365 if str(t.get("pair")) in BASE_PAIRS]
    unique_base_dates = []
    seen = set()
    for trade in sorted(base_later, key=lambda t: str(t.get("open_date"))):
        key = (trade.get("pair"), trade.get("open_date"), tag_key(trade))
        if key in seen:
            continue
        seen.add(key)
        unique_base_dates.append(trade)
    before_90 = []
    inside_90 = []
    for trade in unique_base_dates:
        open_ts = parse_date(trade.get("open_date"))
        if start90 is not None and open_ts is not None and open_ts < start90:
            before_90.append(trade)
        else:
            inside_90.append(trade)
    expanded_same_later = [t for t in expanded180 + expanded365 if str(t.get("pair")) not in BASE_PAIRS]
    lines = [
        "# 90d No-Signal Analysis",
        "",
        "Scope: base 5 pairs are BTC/USDT, ETH/USDT, SOL/USDT, XRP/USDT, ADA/USDT.",
        f"Base 90d timerange: `{group_timerange(summary, 'base_90d')}`.",
        "",
        "## Result",
        f"- Base 90d trades: `{len(base90)}`.",
        f"- Base 180d trades on the same 5 pairs: `{len(base180)}`.",
        f"- Base 365d trades on the same 5 pairs: `{len(base365)}`.",
        f"- Expanded 180d trades: `{len(expanded180)}`.",
        f"- Expanded 365d trades: `{len(expanded365)}`.",
        "",
        "## Trigger Dates On The Same 5 Pairs",
        "| pair | open_date | enter_tag | group | inside_base_90d |",
        "|---|---|---|---|---|",
    ]
    for trade in unique_base_dates:
        open_ts = parse_date(trade.get("open_date"))
        inside = bool(start90 is not None and open_ts is not None and open_ts >= start90)
        source = "base_180d/base_365d"
        lines.append(f"| `{trade.get('pair')}` | `{trade.get('open_date')}` | `{tag_key(trade)}` | `{source}` | `{inside}` |")
    if not unique_base_dates:
        lines.append("| N/A | N/A | N/A | N/A | N/A |")
    lines += [
        "",
        "## Interpretation",
    ]
    if len(base90) == 0 and before_90 and not inside_90:
        conclusion = "The 90d no-trade result is explained by time-window coverage: all later same-pair triggers occurred before the 90d window started."
    elif len(base90) == 0 and expanded_same_later:
        conclusion = "The 90d no-trade result is explained by both a short time window and a narrow pairlist; expanded pairs produced opportunities outside the original universe."
    elif len(base90) == 0:
        conclusion = "The 90d no-trade result remains a no-signal sample for the original universe; the next layer is condition-level inspection."
    else:
        conclusion = "Base 90d was not a no-trade sample in the parsed exports."
    lines.append(f"- {conclusion}")
    lines.append("- This does not mean the strategy is valid or invalid; it only explains why this sample had zero entries.")
    NO_SIGNAL_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "base_90d_trades": len(base90),
        "base_180d_trades": len(base180),
        "base_365d_trades": len(base365),
        "expanded_180d_trades": len(expanded180),
        "expanded_365d_trades": len(expanded365),
        "same_pair_trigger_count": len(unique_base_dates),
        "same_pair_triggers_before_90d": len(before_90),
        "same_pair_triggers_inside_90d": len(inside_90),
        "conclusion": conclusion,
    }


def parse_strategy_metadata(text: str) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    patterns = {
        "timeframe": r"^\s*timeframe\s*=\s*['\"]([^'\"]+)['\"]",
        "startup_candle_count": r"^\s*startup_candle_count.*=\s*([0-9]+)",
        "info_timeframes": r"^\s*info_timeframes\s*=\s*(\[[^\]]+\])",
        "btc_info_timeframes": r"^\s*btc_info_timeframes\s*=\s*(\[[^\]]+\])",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text, re.M)
        if not m:
            continue
        if key.endswith("timeframes"):
            meta[key] = re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))
        elif key == "startup_candle_count":
            meta[key] = int(m.group(1))
        else:
            meta[key] = m.group(1)
    return meta


def line_number(text: str, pattern: str) -> int | None:
    for i, line in enumerate(text.splitlines(), 1):
        if re.search(pattern, line):
            return i
    return None


def write_strategy_conditions(primary_tags: list[dict[str, Any]]) -> dict[str, Any]:
    path = strategy_path()
    text = path.read_text(encoding="utf-8", errors="ignore")
    meta = parse_strategy_metadata(text)
    pop_line = line_number(text, r"def populate_entry_trend")
    enter_assign_line = line_number(text, r"df\.loc\[:, \"enter_long\"\].*_or_entry_conditions")
    tag_assign_line = line_number(text, r"df\.loc\[:, \"enter_tag\"\]")
    used_tags = [row["enter_tag"] for row in primary_tags]
    used_groups = Counter()
    for tag in used_tags:
        for token in str(tag).split():
            for name, values in TAG_GROUPS.items():
                if token in values:
                    used_groups[name] += 1
    lines = [
        "# Strategy Conditions",
        "",
        f"Strategy file: `{path}`",
        f"`populate_entry_trend` starts near line `{pop_line}`.",
        f"`enter_long` OR aggregation is near line `{enter_assign_line}`.",
        f"`enter_tag` assignment is near line `{tag_assign_line}`.",
        "",
        "## Static Metadata",
        f"- Base timeframe: `{meta.get('timeframe', 'unknown')}`.",
        f"- Informative timeframes: `{meta.get('info_timeframes', [])}`.",
        f"- BTC informative timeframes: `{meta.get('btc_info_timeframes', [])}`.",
        f"- Startup candles declared in source: `{meta.get('startup_candle_count', 'unknown')}`.",
        "",
        "## How Entry Tags Work",
        "- The strategy builds many long entry condition blocks.",
        "- Each block is an AND-combination of indicator filters plus volume > 0.",
        "- Matching blocks append their numeric condition id into `enter_tag`.",
        "- Final `enter_long` is the OR of all long condition blocks.",
        "- A multi-number tag such as `6 102 141` means multiple condition families were true on the same candle.",
        "",
        "## Tag Families",
        "| family | tags | rough meaning |",
        "|---|---|---|",
        "| normal | 1-13 | baseline long setups with local oscillator/trend filters |",
        "| pump | 21-26 | pump or extended-move handling |",
        "| quick | 41-53 | quicker reversal/continuation setups |",
        "| rebuy | 61,62,63,65 | rebuy / position continuation context |",
        "| high_profit | 81,82 | high-profit mode entries |",
        "| rapid | 101-110 | rapid move logic |",
        "| grind | 120 | long grinding logic; can hold much longer |",
        "| btc | 121 | BTC-environment dependent logic |",
        "| top_coins | 141-145 | top-coin specific setups |",
        "| scalp | 161-163 | scalp setups |",
        "",
        "## Tags Observed In The Primary Sample",
        "| enter_tag | tag_groups | occurrences |",
        "|---|---|---:|",
    ]
    for row in primary_tags:
        lines.append(f"| `{row['enter_tag']}` | `{row['tag_groups']}` | {row['occurrences']} |")
    lines += [
        "",
        "## Why Signals Are Sparse",
        "- Conditions are strict: most entry blocks require several indicators to agree at once.",
        "- Many checks use informative 15m/1h/4h/1d columns, so a 5m candle may fail because a higher timeframe state is not aligned.",
        "- The source references BTC informative data; broad-market filters can suppress otherwise local pair signals.",
        "- Startup candle requirements reduce the usable beginning of a sample, especially when 1d and 4h informative windows are involved.",
        "- The observed dominant tags are top_coins, rapid, rebuy, grind and normal families, so opportunities appear clustered around specific market regimes rather than every short window.",
        "",
        "## Important Limit",
        "This is a static source-level explanation plus parsed backtest behavior. It does not rewrite strategy logic and does not prove future profitability.",
    ]
    CONDITIONS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "strategy_path": str(path),
        "metadata": meta,
        "populate_entry_trend_line": pop_line,
        "enter_long_aggregation_line": enter_assign_line,
        "enter_tag_assignment_line": tag_assign_line,
        "observed_tag_families": dict(used_groups),
    }


def top_items(rows: list[dict[str, Any]], key: str, n: int = 8) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (-float(r.get(key, 0) or 0), str(r.get("enter_tag") or r.get("pair") or "")))[:n]


def write_main_report(
    summary: dict[str, Any],
    no_trade: dict[str, Any],
    primary_group: str,
    enter_rows: list[dict[str, Any]],
    pair_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    no_signal: dict[str, Any],
    conditions: dict[str, Any],
) -> None:
    top_tags = top_items(enter_rows, "occurrences", 10)
    top_pairs = top_items(pair_rows, "trades_count", 10)
    regimes = Counter(str(r.get("market_regime")) for r in context_rows)
    typical = sorted(context_rows, key=lambda r: abs(float(r.get("profit_pct") or 0)), reverse=True)[:8]
    lines = [
        "# Strategy Explainability Report",
        "",
        f"Generated: `{utcnow()}`",
        "",
        "This report explains observed strategy behavior only. It is not investment advice, not a live-trading recommendation, and not proof of future returns.",
        "",
        "## Summary Conclusion",
        f"- Primary analysis sample: `{primary_group}`.",
        f"- 90d no-trade reason: {no_signal.get('conclusion')}.",
        "- Expanding the sample created entries because the longer time windows covered sparse NFI entry regimes and the wider pairlist added pairs that matched those regimes.",
        "- Recommendation: condition-level explanation is now more useful than blind sample expansion. Keep dry-run forward observation before any parameter work.",
        "",
        "## Existing Sample Matrix",
        "| group | timerange | enter_long | trades |",
        "|---|---|---:|---:|",
    ]
    for item in summary.get("groups", []):
        lines.append(
            f"| `{item.get('group')}` | `{item.get('timerange')}` | {item.get('enter_long_count')} | {item.get('trades_count')} |"
        )
    lines += [
        "",
        "## Enter Tag Distribution",
        "| enter_tag | groups | occurrences | pairs | avg_profit_pct | win_rate_pct |",
        "|---|---|---:|---|---:|---:|",
    ]
    for row in top_tags:
        lines.append(
            f"| `{row['enter_tag']}` | `{row['tag_groups']}` | {row['occurrences']} | `{row['pairs']}` | {row['avg_profit_pct']} | {row['win_rate_pct']} |"
        )
    lines += [
        "",
        "## Pair Distribution",
        "| pair | trades | total_profit_abs | most_common_enter_tag | no_90d_but_later |",
        "|---|---:|---:|---|---|",
    ]
    for row in top_pairs:
        lines.append(
            f"| `{row['pair']}` | {row['trades_count']} | {row['total_profit_abs']} | `{row['most_common_enter_tag']}` | `{row['no_signal_90d_but_later_signal']}` |"
        )
    lines += [
        "",
        "## Trade Context",
        f"- Market regime counts: `{dict(regimes)}`.",
        "- RSI/EMA values in trade_context.csv are recomputed from local 5m OHLCV, not imported from the strategy's full analyzed dataframe.",
        "- Informative 15m/1h/4h/1d strategy columns are explained statically in strategy_conditions.md because exported trades do not include full analyzed indicator frames.",
        "",
        "## Typical Trades",
        "| pair | open_date | enter_tag | profit_pct | regime | pre_48_return_pct | rsi_14 |",
        "|---|---|---|---:|---|---:|---:|",
    ]
    for row in typical:
        lines.append(
            f"| `{row['pair']}` | `{row['open_date']}` | `{row['enter_tag']}` | {row['profit_pct']} | `{row['market_regime']}` | {row['pre_48_return_pct']} | {row['rsi_14_recomputed']} |"
        )
    lines += [
        "",
        "## What Most Likely Limits Signal Count",
        "- Multi-timeframe agreement: 5m entries depend on 15m/1h/4h/1d state.",
        "- BTC/broad-market filters can suppress local pair signals.",
        "- Top-coin and grinding families are sparse and clustered in time.",
        "- Startup candle needs and higher timeframe history make short timeranges less representative.",
        "",
        "## Next Step Recommendation",
        "- Do not move to return optimization yet; first inspect the specific condition families that actually fired: top_coins, rapid, rebuy, grind and normal tags.",
        "- Continued dry-run forward observation is useful, especially with the 20-pair sample universe.",
        "- Further sample expansion is secondary; 365d x 20 pairs already changed the original no-trade conclusion.",
        "",
        "## Output Files",
        "- `reports/strategy_explain/enter_tag_summary.csv`",
        "- `reports/strategy_explain/pair_signal_summary.csv`",
        "- `reports/strategy_explain/trade_context.csv`",
        "- `reports/strategy_explain/no_signal_90d_analysis.md`",
        "- `reports/strategy_explain/strategy_conditions.md`",
        "- `reports/strategy_explain/strategy_explain_summary.json`",
        "- `reports/strategy_explain/strategy_explain_logs.txt`",
    ]
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rec = Recorder()
    rec.section("Strategy explainability")
    rec.log(f"project: {PROJECT_ROOT}")
    rec.log(f"generated_at: {utcnow()}")
    runtime_before = RUNTIME_CONFIG.read_bytes()
    pre_safety = assert_safety("before", rec)
    summary = sample_summary()
    no_trade = no_trade_summary()
    exports = parse_exports(rec)
    primary_group = preferred_primary_group(exports)
    if not primary_group:
        raise RuntimeError("No Freqtrade export zips found in reports.")
    primary_trades = list(exports[primary_group].get("trades", []))
    rec.log(f"primary_group: {primary_group}")
    rec.log(f"primary_trade_count: {len(primary_trades)}")

    enter_rows = write_enter_tag_summary(primary_trades)
    pair_rows = write_pair_summary(primary_trades, exports)
    context_rows = write_trade_context(primary_trades)
    no_signal = write_no_signal_analysis(exports, summary)
    conditions = write_strategy_conditions(enter_rows)

    post_safety = assert_safety("after", rec)
    runtime_untouched = runtime_before == RUNTIME_CONFIG.read_bytes()
    if not runtime_untouched:
        raise RuntimeError("Runtime config changed during explainability run.")

    summary_out = {
        "generated_at": utcnow(),
        "primary_group": primary_group,
        "primary_trade_count": len(primary_trades),
        "safe_config": all(pre_safety["checks"].values()) and all(post_safety["checks"].values()),
        "pre_safety": pre_safety,
        "post_safety": post_safety,
        "runtime_config_untouched": runtime_untouched,
        "no_trade_summary": {
            "enter_long_count": no_trade.get("enter_long_count"),
            "trades_count": no_trade.get("trades_count"),
            "likely_causes": no_trade.get("likely_causes", []),
        },
        "sample_groups": summary.get("groups", []),
        "no_signal_90d_analysis": no_signal,
        "top_enter_tags": top_items(enter_rows, "occurrences", 10),
        "top_pairs": top_items(pair_rows, "trades_count", 10),
        "market_regime_counts": dict(Counter(str(r.get("market_regime")) for r in context_rows)),
        "strategy_conditions": conditions,
        "recommendation": {
            "continue_expanding_sample": "secondary",
            "enter_condition_level_analysis": True,
            "enter_parameter_optimization": False,
            "continue_dry_run_forward_observation": True,
        },
        "outputs": {
            "enter_tag_summary": str(ENTER_TAG_CSV),
            "pair_signal_summary": str(PAIR_CSV),
            "trade_context": str(TRADE_CONTEXT_CSV),
            "no_signal_90d_analysis": str(NO_SIGNAL_MD),
            "strategy_conditions": str(CONDITIONS_MD),
            "report": str(REPORT_MD),
            "summary": str(SUMMARY_JSON),
            "logs": str(LOG_TXT),
        },
    }
    SUMMARY_JSON.write_text(json.dumps(summary_out, indent=2, ensure_ascii=True), encoding="utf-8")
    write_main_report(summary, no_trade, primary_group, enter_rows, pair_rows, context_rows, no_signal, conditions)

    rec.section("Outputs")
    for path in (ENTER_TAG_CSV, PAIR_CSV, TRADE_CONTEXT_CSV, NO_SIGNAL_MD, CONDITIONS_MD, REPORT_MD, SUMMARY_JSON, LOG_TXT):
        rec.log(str(path))
    rec.write()
    return 0


if __name__ == "__main__":
    sys.exit(main())
