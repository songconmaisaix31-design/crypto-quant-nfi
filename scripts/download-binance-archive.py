#!/usr/bin/env python3
"""Download Binance public spot kline archives with checksum verification.

This is a fallback data source. It only targets https://data.binance.vision/data/spot/.
"""
import argparse, hashlib, os, sys, urllib.request
from datetime import date, timedelta
from pathlib import Path

BASE = 'https://data.binance.vision/data/spot'
PAIRS = ['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','ADAUSDT']
TIMEFRAMES = ['5m','15m','1h','4h','1d']
CACHE = Path('/mnt/d/AI-Workspace/Projects/crypto-quant-nfi/user_data/archive_cache/binance')

def month_iter(start: date, end: date):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        yield cur.year, cur.month
        cur = date(cur.year + (cur.month == 12), 1 if cur.month == 12 else cur.month + 1, 1)

def download(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as r, open(path, 'wb') as f:
        f.write(r.read())

def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def get_file(kind, pair, tf, name):
    url=f'{BASE}/{kind}/klines/{pair}/{tf}/{name}'
    path=CACHE/kind/'klines'/pair/tf/name
    sum_path=path.with_name(path.name+'.CHECKSUM')
    if not path.exists() or path.stat().st_size == 0:
        download(url, path)
    if not sum_path.exists() or sum_path.stat().st_size == 0:
        download(url+'.CHECKSUM', sum_path)
    expected=sum_path.read_text(errors='ignore').split()[0]
    actual=sha256(path)
    if expected != actual:
        path.unlink(missing_ok=True)
        download(url, path)
        actual=sha256(path)
        if expected != actual:
            raise RuntimeError(f'checksum failed: {path}')
    print(f'[PASS] {path}')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--start', default='2023-12-01')
    ap.add_argument('--end', default=date.today().isoformat())
    args=ap.parse_args()
    start=date.fromisoformat(args.start); end=date.fromisoformat(args.end)
    for pair in PAIRS:
        for tf in TIMEFRAMES:
            for y,m in month_iter(start, end):
                name=f'{pair}-{tf}-{y}-{m:02d}.zip'
                try:
                    get_file('monthly', pair, tf, name)
                except Exception as exc:
                    print(f'[WARN] monthly unavailable {name}: {exc}', file=sys.stderr)
    return 0
if __name__ == '__main__':
    raise SystemExit(main())