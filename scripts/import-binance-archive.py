#!/usr/bin/env python3
"""Import Binance archive kline ZIPs into Freqtrade feather files."""
import argparse, zipfile
from pathlib import Path
import pandas as pd
from freqtrade.data.history.datahandlers import get_datahandler
from freqtrade.enums import CandleType

ROOT=Path('/mnt/d/AI-Workspace/Projects/crypto-quant-nfi')
CACHE=ROOT/'user_data/archive_cache/binance'
DATA=ROOT/'user_data/data/binance'
PAIRS={'BTCUSDT':'BTC/USDT','ETHUSDT':'ETH/USDT','SOLUSDT':'SOL/USDT','XRPUSDT':'XRP/USDT','ADAUSDT':'ADA/USDT'}
TIMEFRAMES=['5m','15m','1h','4h','1d']
COLS=['open_time','open','high','low','close','volume','close_time','quote_asset_volume','number_of_trades','taker_buy_base_volume','taker_buy_quote_volume','ignore']

def timestamp_unit(series):
    v=int(series.dropna().iloc[0])
    return 'us' if v > 10_000_000_000_000 else 'ms'

def read_zip(path):
    with zipfile.ZipFile(path) as zf:
        names=[n for n in zf.namelist() if n.endswith('.csv')]
        if not names: raise RuntimeError(f'empty zip: {path}')
        with zf.open(names[0]) as f:
            df=pd.read_csv(f, header=None, names=COLS)
    if df.empty: raise RuntimeError(f'empty csv: {path}')
    unit=timestamp_unit(df['open_time'])
    out=pd.DataFrame({
        'date': pd.to_datetime(df['open_time'], unit=unit, utc=True),
        'open': pd.to_numeric(df['open'], errors='coerce'),
        'high': pd.to_numeric(df['high'], errors='coerce'),
        'low': pd.to_numeric(df['low'], errors='coerce'),
        'close': pd.to_numeric(df['close'], errors='coerce'),
        'volume': pd.to_numeric(df['volume'], errors='coerce'),
    })
    return out

def main():
    handler=get_datahandler(str(DATA), 'feather')
    for symbol,pair in PAIRS.items():
        for tf in TIMEFRAMES:
            frames=[]
            for z in sorted(CACHE.glob(f'*/klines/{symbol}/{tf}/{symbol}-{tf}-*.zip')):
                frames.append(read_zip(z))
            if not frames: continue
            df=pd.concat(frames).sort_values('date').drop_duplicates('date')
            if df[['open','high','low','close','volume']].isna().any().any(): raise RuntimeError(f'NaN in {pair} {tf}')
            if (df[['open','high','low','close']] <= 0).any().any(): raise RuntimeError(f'bad price in {pair} {tf}')
            handler.ohlcv_store(pair, tf, data=df, candle_type=CandleType.SPOT)
            print(f'[PASS] imported {pair} {tf} candles={len(df)}')
if __name__ == '__main__':
    main()