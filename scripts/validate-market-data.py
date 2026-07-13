#!/usr/bin/env python3
import json
import math
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path('/mnt/d/AI-Workspace/Projects/crypto-quant-nfi')
DATA_DIR = PROJECT_ROOT / 'user_data/data/binance'
REPORT_JSON = PROJECT_ROOT / 'user_data/logs/data-quality-report.json'
REPORT_TXT = PROJECT_ROOT / 'user_data/logs/data-quality-report.txt'
PAIRS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT']
TIMEFRAMES = ['5m', '15m', '1h', '4h', '1d']
TF_MINUTES = {'5m': 5, '15m': 15, '1h': 60, '4h': 240, '1d': 1440}
STARTUP_DAYS = 800
BACKTEST_DAYS = 90
BUFFER_DAYS = 30
MIN_DAYS = STARTUP_DAYS + BACKTEST_DAYS + BUFFER_DAYS

def filename(pair, timeframe):
    return DATA_DIR / f"{pair.replace('/', '_')}-{timeframe}.feather"

def check_file(pair, timeframe):
    path = filename(pair, timeframe)
    item = {'pair': pair, 'timeframe': timeframe, 'path': str(path), 'exists': path.exists()}
    if not path.exists():
        item['pass'] = False
        item['errors'] = ['missing file']
        return item
    item['size'] = path.stat().st_size
    errors = []
    if item['size'] <= 0:
        errors.append('empty file')
    df = pd.read_feather(path)
    item['candles'] = int(len(df))
    if len(df) == 0:
        errors.append('empty dataframe')
        item['pass'] = False
        item['errors'] = errors
        return item
    if 'date' not in df.columns:
        errors.append('missing date column')
    else:
        df['date'] = pd.to_datetime(df['date'], utc=True)
        df = df.sort_values('date')
        start = df['date'].iloc[0]
        end = df['date'].iloc[-1]
        item['start'] = start.isoformat()
        item['end'] = end.isoformat()
        item['days'] = round((end - start).total_seconds() / 86400, 2)
        if not df['date'].is_monotonic_increasing:
            errors.append('date not increasing')
        dupes = int(df['date'].duplicated().sum())
        item['duplicates'] = dupes
        if dupes:
            errors.append(f'duplicate timestamps: {dupes}')
        expected_delta = pd.Timedelta(minutes=TF_MINUTES[timeframe])
        gaps = df['date'].diff().dropna()
        missing = gaps[gaps > expected_delta]
        missing_candles = int(((missing / expected_delta) - 1).sum()) if len(missing) else 0
        item['missing_candles'] = missing_candles
        item['gap_count'] = int(len(missing))
        item['longest_gap_minutes'] = int((missing.max() / pd.Timedelta(minutes=1))) if len(missing) else 0
        if item['days'] < MIN_DAYS - 1:
            errors.append(f'data range too short: {item["days"]} days < {MIN_DAYS}')
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col not in df.columns:
            errors.append(f'missing {col}')
        else:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            nans = int(df[col].isna().sum())
            if nans:
                errors.append(f'{col} NaN count: {nans}')
    if all(c in df.columns for c in ['open','high','low','close','volume']):
        if ((df[['open','high','low','close']] <= 0).any(axis=1)).any():
            errors.append('non-positive OHLC price')
        if (df['volume'] < 0).any():
            errors.append('negative volume')
        if (df['high'] < df[['open','close','low']].max(axis=1)).any():
            errors.append('high lower than open/close/low')
        if (df['low'] > df[['open','close','high']].min(axis=1)).any():
            errors.append('low higher than open/close/high')
    item['errors'] = errors
    item['pass'] = not errors
    return item

def main():
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    rows = [check_file(pair, tf) for pair in PAIRS for tf in TIMEFRAMES]
    ok = all(row['pass'] for row in rows)
    report = {'pass': ok, 'required_days': MIN_DAYS, 'pairs': PAIRS, 'timeframes': TIMEFRAMES, 'files': rows}
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding='utf-8')
    lines = [f"PASS={ok}", f"required_days={MIN_DAYS}", f"files={len(rows)}"]
    for row in rows:
        status = 'PASS' if row['pass'] else 'FAIL'
        lines.append(f"{status} {row['pair']} {row['timeframe']} candles={row.get('candles')} days={row.get('days')} missing={row.get('missing_candles')} gaps={row.get('gap_count')} longest_gap_min={row.get('longest_gap_minutes')}")
        for err in row.get('errors', []):
            lines.append(f"  - {err}")
    REPORT_TXT.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))
    return 0 if ok else 1

if __name__ == '__main__':
    sys.exit(main())