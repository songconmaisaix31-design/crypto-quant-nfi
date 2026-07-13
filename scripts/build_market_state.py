#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
RUNTIME_CONFIG = PROJECT_ROOT / "user_data/config.runtime.json"
SAMPLE_SUMMARY = PROJECT_ROOT / "reports/sample_validation/sample_validation_summary.json"
DATA_DIR = PROJECT_ROOT / "user_data/data/binance"
USER_OUT = PROJECT_ROOT / "user_data/market_state"
REPORT_OUT = PROJECT_ROOT / "reports/market_state"
HISTORY_CSV = USER_OUT / "market_state_history.csv"
LATEST_JSON = USER_OUT / "market_state_latest.json"
PAIR_QUALITY_CSV = REPORT_OUT / "pair_quality_scores.csv"
REPORT_MD = REPORT_OUT / "market_state_report.md"
SUMMARY_JSON = REPORT_OUT / "market_state_summary.json"
COVERAGE_CSV = REPORT_OUT / "regime_coverage_matrix.csv"


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


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
    if not all(checks.values()):
        raise RuntimeError(f"Unsafe runtime config: {checks}")
    return checks


def pair_to_file(pair: str) -> Path:
    return DATA_DIR / f"{pair.replace('/', '_')}-1d.feather"


def load_pairs() -> list[str]:
    summary = load_json(SAMPLE_SUMMARY, {})
    pairs = summary.get("expanded_pairs") or []
    if not pairs:
        pairs = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"]
    if "BTC/USDT" not in pairs:
        pairs.insert(0, "BTC/USDT")
    return list(dict.fromkeys(pairs))


def load_ohlcv(pair: str) -> pd.DataFrame:
    path = pair_to_file(pair)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_feather(path)
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.date
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = df["close"]
    volume = df["volume"]
    df["return_1d"] = close.pct_change(1) * 100
    df["return_3d"] = close.pct_change(3) * 100
    df["return_7d"] = close.pct_change(7) * 100
    df["return_30d"] = close.pct_change(30) * 100
    df["ema20"] = close.ewm(span=20, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()
    df["ema200"] = close.ewm(span=200, adjust=False).mean()
    high30 = df["high"].rolling(30, min_periods=10).max()
    df["drawdown_from_30d_high"] = ((close / high30) - 1) * 100
    true_range_pct = ((df["high"] - df["low"]) / close.replace(0, math.nan)) * 100
    df["atr_percent"] = true_range_pct.rolling(14, min_periods=5).mean()
    ret = close.pct_change()
    df["volatility_7d"] = ret.rolling(7, min_periods=5).std() * 100
    df["volatility_30d"] = ret.rolling(30, min_periods=10).std() * 100
    vol_mean = volume.rolling(30, min_periods=10).mean()
    vol_std = volume.rolling(30, min_periods=10).std()
    df["volume_zscore"] = (volume - vol_mean) / vol_std.replace(0, math.nan)
    df["volume_change_24h"] = volume.pct_change(1) * 100
    df["volume_change_7d"] = volume.pct_change(7) * 100
    return df


def fetch_fear_greed() -> dict[str, Any]:
    try:
        with urllib.request.urlopen("https://api.alternative.me/fng/?limit=1&format=json", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        item = (data.get("data") or [{}])[0]
        return {
            "available": True,
            "score": float(item.get("value")),
            "classification": item.get("value_classification"),
            "timestamp": item.get("timestamp"),
        }
    except Exception as exc:
        return {"available": False, "error": repr(exc)}


def pair_quality(row: pd.Series, btc_row: pd.Series) -> float:
    score = 50.0
    score += clamp(float(row.get("return_7d") or 0), -20, 20) * 0.6
    score += clamp(float(row.get("return_30d") or 0), -40, 40) * 0.25
    score += clamp(float(row.get("return_7d") or 0) - float(btc_row.get("return_7d") or 0), -20, 20) * 0.6
    if float(row.get("close") or 0) > float(row.get("ema20") or math.inf):
        score += 8
    if float(row.get("close") or 0) > float(row.get("ema50") or math.inf):
        score += 8
    score += max(float(row.get("drawdown_from_30d_high") or 0), -50) * 0.25
    atr = float(row.get("atr_percent") or 0)
    if atr > 10:
        score -= min((atr - 10) * 2, 20)
    vz = abs(float(row.get("volume_zscore") or 0))
    if vz > 3:
        score -= min((vz - 3) * 8, 20)
    return round(clamp(score), 4)


def score_components(date: Any, btc: pd.Series, day_pairs: pd.DataFrame, fear_greed: dict[str, Any]) -> dict[str, float | None]:
    btc_trend = 50.0
    if bool(btc["close"] > btc["ema50"]):
        btc_trend += 20
    else:
        btc_trend -= 20
    if bool(btc["close"] > btc["ema200"]):
        btc_trend += 15
    else:
        btc_trend -= 15
    btc_trend += clamp(float(btc.get("return_7d") or 0), -20, 20)
    breadth = float(
        pd.Series(
            [
                day_pairs["pair_above_ema20"].mean() * 100,
                day_pairs["pair_above_ema50"].mean() * 100,
                day_pairs["pair_positive_24h"].mean() * 100,
                day_pairs["pair_positive_7d"].mean() * 100,
            ]
        ).mean()
    )
    vol_z = float(day_pairs["volume_zscore"].median(skipna=True) or 0)
    volume_score = clamp(50 + vol_z * 10)
    atr = float(day_pairs["pair_atr_percent"].median(skipna=True) or 0)
    btc_vol = float(btc.get("volatility_30d") or 0)
    volatility_score = clamp(75 - max(atr, btc_vol) * 6)
    rel = float(day_pairs["pair_vs_btc_return_7d"].median(skipna=True) or 0)
    rel_score = clamp(50 + rel * 2)
    fg_score = fear_greed.get("score") if fear_greed.get("available") else None
    if fg_score is not None:
        total = 0.20 * float(fg_score) + 0.25 * btc_trend + 0.20 * breadth + 0.15 * volume_score + 0.10 * volatility_score + 0.10 * rel_score
    else:
        total = 0.30 * btc_trend + 0.25 * breadth + 0.20 * volume_score + 0.15 * volatility_score + 0.10 * rel_score
    return {
        "fear_greed_score": None if fg_score is None else round(float(fg_score), 4),
        "btc_trend_score": round(clamp(btc_trend), 4),
        "market_breadth_score": round(clamp(breadth), 4),
        "volume_score": round(clamp(volume_score), 4),
        "volatility_score": round(clamp(volatility_score), 4),
        "pair_relative_strength_score": round(clamp(rel_score), 4),
        "market_sentiment_score": round(clamp(total), 4),
    }


def regimes(score: float, btc: pd.Series, row: dict[str, Any]) -> tuple[str, list[str]]:
    tags: list[str] = []
    if score < 25 or float(btc.get("drawdown_from_30d_high") or 0) < -20:
        tags.append("panic")
    elif score < 40:
        tags.append("fear")
    elif score >= 80:
        tags.append("overheated")
    elif score >= 65:
        tags.append("greed")
    else:
        tags.append("neutral")
    if bool(row["btc_above_ema50"]) and bool(row["btc_above_ema200"]) and float(btc.get("return_7d") or 0) > 0:
        tags.append("trend_up")
    if (not bool(row["btc_above_ema50"])) and float(btc.get("return_7d") or 0) < 0:
        tags.append("trend_down")
    if score >= 60 and float(row["percent_pairs_above_ema50"]) >= 55:
        tags.append("risk_on")
    if score < 45 or float(row["percent_pairs_above_ema50"]) < 40:
        tags.append("risk_off")
    if float(row["median_pair_atr_percent"]) > 6 or float(btc.get("atr_percent") or 0) > 6:
        tags.append("high_volatility")
    if 40 <= score <= 60 and float(row["median_pair_atr_percent"]) < 4:
        tags.append("compression")
    priority = ["panic", "overheated", "greed", "fear", "risk_off", "risk_on", "trend_up", "trend_down", "neutral"]
    primary = next((tag for tag in priority if tag in tags), "neutral")
    return primary, list(dict.fromkeys(tags))


def main() -> int:
    USER_OUT.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.mkdir(parents=True, exist_ok=True)
    before = RUNTIME_CONFIG.read_bytes()
    safe = safety()
    pairs = load_pairs()
    frames = {pair: add_indicators(load_ohlcv(pair)) for pair in pairs}
    frames = {pair: df for pair, df in frames.items() if not df.empty}
    if "BTC/USDT" not in frames:
        raise RuntimeError("BTC/USDT 1d data is required.")
    btc = frames["BTC/USDT"].set_index("date")
    fear_greed = fetch_fear_greed()
    pair_rows: list[dict[str, Any]] = []
    market_rows: list[dict[str, Any]] = []
    for date, btc_row in btc.iterrows():
        daily = []
        for pair, df in frames.items():
            if pair == "BTC/USDT":
                continue
            hit = df[df["date"] == date]
            if hit.empty:
                continue
            r = hit.iloc[-1]
            q = pair_quality(r, btc_row)
            item = {
                "date": str(date),
                "pair": pair,
                "pair_return_1d": round(float(r.get("return_1d") or 0), 6),
                "pair_return_7d": round(float(r.get("return_7d") or 0), 6),
                "pair_return_30d": round(float(r.get("return_30d") or 0), 6),
                "pair_vs_btc_return_7d": round(float(r.get("return_7d") or 0) - float(btc_row.get("return_7d") or 0), 6),
                "pair_vs_btc_return_30d": round(float(r.get("return_30d") or 0) - float(btc_row.get("return_30d") or 0), 6),
                "pair_above_ema20": bool(r["close"] > r["ema20"]),
                "pair_above_ema50": bool(r["close"] > r["ema50"]),
                "pair_positive_24h": bool(float(r.get("return_1d") or 0) > 0),
                "pair_positive_7d": bool(float(r.get("return_7d") or 0) > 0),
                "pair_drawdown_from_30d_high": round(float(r.get("drawdown_from_30d_high") or 0), 6),
                "pair_atr_percent": round(float(r.get("atr_percent") or 0), 6),
                "volume_zscore": round(float(r.get("volume_zscore") or 0), 6),
                "volume_change_24h": round(float(r.get("volume_change_24h") or 0), 6),
                "volume_change_7d": round(float(r.get("volume_change_7d") or 0), 6),
                "pair_quality_score": q,
            }
            pair_rows.append(item)
            daily.append(item)
        if not daily:
            continue
        day_pairs = pd.DataFrame(daily)
        comps = score_components(date, btc_row, day_pairs, fear_greed)
        row = {
            "date": str(date),
            "btc_return_1d": round(float(btc_row.get("return_1d") or 0), 6),
            "btc_return_3d": round(float(btc_row.get("return_3d") or 0), 6),
            "btc_return_7d": round(float(btc_row.get("return_7d") or 0), 6),
            "btc_ema20": round(float(btc_row.get("ema20") or 0), 8),
            "btc_ema50": round(float(btc_row.get("ema50") or 0), 8),
            "btc_ema200": round(float(btc_row.get("ema200") or 0), 8),
            "btc_above_ema50": bool(btc_row["close"] > btc_row["ema50"]),
            "btc_above_ema200": bool(btc_row["close"] > btc_row["ema200"]),
            "btc_drawdown_from_30d_high": round(float(btc_row.get("drawdown_from_30d_high") or 0), 6),
            "btc_atr_percent": round(float(btc_row.get("atr_percent") or 0), 6),
            "btc_volatility_7d": round(float(btc_row.get("volatility_7d") or 0), 6),
            "btc_volatility_30d": round(float(btc_row.get("volatility_30d") or 0), 6),
            "percent_pairs_above_ema20": round(float(day_pairs["pair_above_ema20"].mean() * 100), 6),
            "percent_pairs_above_ema50": round(float(day_pairs["pair_above_ema50"].mean() * 100), 6),
            "percent_pairs_positive_24h": round(float(day_pairs["pair_positive_24h"].mean() * 100), 6),
            "percent_pairs_positive_7d": round(float(day_pairs["pair_positive_7d"].mean() * 100), 6),
            "median_pair_return_24h": round(float(day_pairs["pair_return_1d"].median()), 6),
            "median_pair_return_7d": round(float(day_pairs["pair_return_7d"].median()), 6),
            "median_pair_atr_percent": round(float(day_pairs["pair_atr_percent"].median()), 6),
        }
        row.update(comps)
        primary, tags = regimes(float(row["market_sentiment_score"]), btc_row, row)
        row["primary_regime"] = primary
        row["regime_tags"] = " ".join(tags)
        row["evidence"] = f"score={row['market_sentiment_score']}; btc_above_ema50={row['btc_above_ema50']}; breadth50={row['percent_pairs_above_ema50']}; atr={row['median_pair_atr_percent']}"
        market_rows.append(row)
    hist = pd.DataFrame(market_rows)
    pairq = pd.DataFrame(pair_rows)
    hist.to_csv(HISTORY_CSV, index=False)
    pairq.to_csv(PAIR_QUALITY_CSV, index=False)
    latest = hist.iloc[-1].to_dict() if len(hist) else {}
    latest["fear_greed_source"] = fear_greed
    LATEST_JSON.write_text(json.dumps(latest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    sample = load_json(SAMPLE_SUMMARY, {})
    expanded = next((g for g in sample.get("groups", []) if g.get("group") == "expanded_365d"), {})
    start, end = (expanded.get("timerange") or "-").split("-", 1)
    start_date = pd.to_datetime(start, format="%Y%m%d").date() if start else None
    end_date = pd.to_datetime(end, format="%Y%m%d").date() if end else None
    window = hist[(pd.to_datetime(hist["date"]).dt.date >= start_date) & (pd.to_datetime(hist["date"]).dt.date <= end_date)] if start_date and end_date and len(hist) else hist
    required = ["trend_up", "trend_down", "risk_on", "risk_off", "fear", "greed", "high_volatility", "neutral"]
    coverage_rows = []
    for tag in required:
        mask = window["regime_tags"].astype(str).str.contains(rf"(^| ){tag}( |$)", regex=True) if len(window) else pd.Series([], dtype=bool)
        coverage_rows.append({"regime": tag, "covered": bool(mask.any()), "days": int(mask.sum() if len(mask) else 0)})
    coverage = pd.DataFrame(coverage_rows)
    coverage.to_csv(COVERAGE_CSV, index=False)
    summary = {
        "safe_config": safe,
        "pairs": pairs,
        "history_rows": len(hist),
        "pair_quality_rows": len(pairq),
        "latest": latest,
        "fear_greed": fear_greed,
        "coverage_window": expanded.get("timerange"),
        "regime_coverage": coverage_rows,
        "missing_regimes": [r["regime"] for r in coverage_rows if not r["covered"]],
        "local_only": not fear_greed.get("available", False),
        "runtime_config_untouched": before == RUNTIME_CONFIG.read_bytes(),
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    top_pairs = pairq[pairq["date"] == latest.get("date")].sort_values("pair_quality_score", ascending=False).head(10) if len(pairq) and latest else pd.DataFrame()
    lines = [
        "# Market State Report",
        "",
        "This report is local/offline evidence for pre-live gating. It does not enable live trading.",
        "",
        f"- History rows: `{len(hist)}`",
        f"- Pair quality rows: `{len(pairq)}`",
        f"- Latest date: `{latest.get('date')}`",
        f"- Latest score: `{latest.get('market_sentiment_score')}`",
        f"- Latest primary regime: `{latest.get('primary_regime')}`",
        f"- Fear & Greed source: `{fear_greed}`",
        "",
        "## 365d Regime Coverage",
        "| regime | covered | days |",
        "|---|---:|---:|",
    ]
    for r in coverage_rows:
        lines.append(f"| `{r['regime']}` | `{r['covered']}` | {r['days']} |")
    lines += ["", "## Top Current Pair Quality", "| pair | quality | return_7d | atr |", "|---|---:|---:|---:|"]
    if len(top_pairs):
        for _, r in top_pairs.iterrows():
            lines.append(f"| `{r['pair']}` | {r['pair_quality_score']} | {r['pair_return_7d']} | {r['pair_atr_percent']} |")
    lines += ["", "Missing regimes are not forced to PASS. If greed/trend_up are missing, longer history such as 2y/3y spot data should be considered."]
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[PASS] wrote {HISTORY_CSV}")
    print(f"[PASS] wrote {LATEST_JSON}")
    print(f"[PASS] wrote {REPORT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
