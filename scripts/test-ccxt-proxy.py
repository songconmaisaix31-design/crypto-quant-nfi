#!/usr/bin/env python3
import asyncio
import contextlib
import os
import sys
import time
from pathlib import Path
from types import MethodType

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"))
LOG_PATH = PROJECT_ROOT / "user_data/logs/network-repair/ccxt-proxy-test.log"
ENV_PATH = PROJECT_ROOT / ".env"


def read_proxy() -> str:
    for line in ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip().startswith("FT_PROXY_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("[FAIL] FT_PROXY_URL is not set in .env")


def ccxt_config(proxy_url: str) -> dict:
    return {
        "enableRateLimit": True,
        "timeout": 60000,
        "httpsProxy": proxy_url,
        "options": {
            "defaultType": "spot",
            "fetchMarkets": {"types": ["spot"]},
        },
    }


def patch_sync(exchange, urls):
    original = exchange.fetch

    def wrapped(self, url, method="GET", headers=None, body=None):
        urls.append(str(url))
        return original(url, method, headers, body)

    exchange.fetch = MethodType(wrapped, exchange)


def patch_async(exchange, urls):
    original = exchange.fetch

    async def wrapped(self, url, method="GET", headers=None, body=None):
        urls.append(str(url))
        return await original(url, method, headers, body)

    exchange.fetch = MethodType(wrapped, exchange)


def summarize_urls(urls):
    return sorted({u.split("/")[2] for u in urls if "://" in u})


def check_no_futures(urls):
    bad = [u for u in urls if "fapi.binance.com" in u or "dapi.binance.com" in u]
    if bad:
        raise RuntimeError("Futures endpoint requested: " + ", ".join(sorted(set(bad))[:5]))


def sync_test(proxy_url, lines):
    import ccxt

    urls = []
    ex = ccxt.binance(ccxt_config(proxy_url))
    patch_sync(ex, urls)
    markets = ex.load_markets()
    check_no_futures(urls)
    market = markets.get("BTC/USDT")
    if not market:
        raise RuntimeError("BTC/USDT missing from sync markets")
    if market.get("spot") is not True:
        raise RuntimeError("BTC/USDT is not marked spot")
    ex.fetch_ticker("BTC/USDT")
    check_no_futures(urls)
    lines.append("[PASS] CCXT sync load_markets")
    lines.append(f"[PASS] CCXT sync markets count: {len(markets)}")
    lines.append("[PASS] BTC/USDT Spot exists")
    lines.append("[PASS] CCXT sync fetch_ticker")
    lines.append("[INFO] sync hosts: " + ", ".join(summarize_urls(urls)))
    return urls


async def async_test(proxy_url, lines):
    import ccxt.async_support as ccxt_async

    urls = []
    ex = ccxt_async.binance(ccxt_config(proxy_url))
    patch_async(ex, urls)
    try:
        markets = await ex.load_markets()
        check_no_futures(urls)
        market = markets.get("BTC/USDT")
        if not market:
            raise RuntimeError("BTC/USDT missing from async markets")
        if market.get("spot") is not True:
            raise RuntimeError("BTC/USDT is not marked spot")
        await ex.fetch_ticker("BTC/USDT")
        check_no_futures(urls)
        lines.append("[PASS] CCXT async load_markets")
        lines.append(f"[PASS] CCXT async markets count: {len(markets)}")
        lines.append("[PASS] CCXT async fetch_ticker")
        lines.append("[INFO] async hosts: " + ", ".join(summarize_urls(urls)))
    finally:
        await ex.close()
    return urls


def main():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    proxy_url = read_proxy()
    if "PORT" in proxy_url:
        raise SystemExit("[FAIL] FT_PROXY_URL contains placeholder PORT")

    lines = ["[INFO] proxy configured: yes"]
    all_urls = []
    rc = 1

    for attempt in range(1, 4):
        lines.append(f"[INFO] CCXT proxy test attempt {attempt}/3")
        try:
            sync_urls = sync_test(proxy_url, lines)
            async_urls = asyncio.run(async_test(proxy_url, lines))
            all_urls = sync_urls + async_urls
            check_no_futures(all_urls)
            lines.append("[PASS] No fapi.binance.com requests")
            lines.append("[PASS] No dapi.binance.com requests")
            rc = 0
            break
        except Exception as exc:
            level = "[WARN]" if attempt < 3 else "[FAIL]"
            lines.append(f"{level} CCXT proxy test attempt {attempt}/3 failed: {exc!r}")
            with contextlib.suppress(Exception):
                lines.append("[INFO] hosts seen: " + ", ".join(summarize_urls(all_urls)))
            if attempt < 3:
                delay = attempt * 5
                lines.append(f"[INFO] retrying after {delay}s")
                time.sleep(delay)

    LOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return rc


if __name__ == "__main__":
    sys.exit(main())
